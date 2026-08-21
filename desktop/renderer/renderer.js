const api = window.pineDesktop;

let config = null;
let currentView = "control";
let railResize = null;
let defaultBroadcastApplied = false;
let appVolume = 0.35;
let desiredBroadcast = "nabu";
let broadcastChanging = false;
let pendingPlayGesture = false;
let mutedNoteAt = 0;
let boothMonitor = localStorage.getItem("pineDesktopBoothMonitor") === "1";
const desktopListenerId = `desktop-${Math.random().toString(36).slice(2, 10)}`;
let desktopTrackId = "";
let desktopClockAt = 0;
let rebuildPct = 0;
let rebuildAnimation = null;
let rebuildTicker = null;
let rebuildParticles = [];
let rebuildStageSeen = new Set();
let rebuildRelaunching = false;

const $ = (id) => document.getElementById(id);

/* #990: COPY, BY WHICHEVER ROAD IS OPEN.
 *
 * navigator.clipboard is undefined on file://, which is where this window
 * is loaded from, so every copy button in here was calling a method that
 * does not exist and swallowing the error. Electron's own clipboard is
 * exposed through the preload and has no secure-context rule; the web API
 * is kept as a second try for when this page is served over http, and a
 * hidden textarea with execCommand is the last resort. Returns whether it
 * actually worked, so a caller can SAY so instead of looking broken. */
async function pineCopy(text) {
  const v = String(text == null ? "" : text);
  if (!v) return false;
  try {
    if (window.pineDesktop && window.pineDesktop.copyText
        && window.pineDesktop.copyText(v)) return true;
  } catch (err) { /* try the next road */ }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(v);
      return true;
    }
  } catch (err) { /* try the next road */ }
  try {
    const pad = document.createElement("textarea");
    pad.value = v;
    pad.setAttribute("readonly", "");
    pad.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(pad);
    pad.select();
    const ok = document.execCommand("copy");
    pad.remove();
    return !!ok;
  } catch (err) {
    return false;
  }
}

const ROUTES = {
  box: { label: "Pine Box", music: "box", voice: "box", reply: "box", voice_device: "pine", box_talk: true },
  // #814: web/app route audio to the PAGE — they must not silently
  // re-point the core DEVICE at the retired pine satellite. They
  // leave voice_device alone; only box/nabu name a device.
  web: { label: "Web page", music: "here", voice: "here", reply: "here", box_talk: false },
  // #979: APPLICATION MEANS ALL OF IT, HERE. music was "off" - the same
  // literal the note below records as the reason the Nabu speaker "sat
  // silent between rounds", left in place on this route. The app played
  // music itself through its own clock-synced player, so the setting was
  // survivable; but it also meant the STATION was producing no music for
  // this route at all, and the moment anything relied on the page feed
  // there was nothing in it. Application now asks for the whole
  // broadcast - the music, the DJs and the replies - out of one place.
  app: { label: "Application", music: "here", voice: "here", reply: "here", box_talk: false },
  // #786: Nabu is the CORE broadcast device — broadcasting to it means the
  // WHOLE station: music and the DJ voice both. music "off" here was why
  // the speaker sat silent between rounds.
  nabu: { label: "Nabu", music: "box", voice: "box", reply: "box", voice_device: "nabu", box_talk: true }
};

const EMBEDDED_ROUTES = {
  box: { djOutput: "box", djVoiceOut: "box", djReplyOut: "box" },
  web: { djOutput: "here", djVoiceOut: "here", djReplyOut: "here" },
  app: { djOutput: "here", djVoiceOut: "here", djReplyOut: "here" },  // #979
  nabu: { djOutput: "nabu", djVoiceOut: "nabu", djReplyOut: "nabu" }
};

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text == null || text === "" ? "unknown" : String(text);
}

// Routing failures must stay visible even in the compact rail, where the
// note line is normally hidden — the .err class forces it back on.
function noteRouteError(text) {
  setText("routeNote", text);
  const note = $("routeNote");
  if (note) note.classList.add("err");
}

function noteRouteOk(text) {
  setText("routeNote", text);
  const note = $("routeNote");
  if (note) note.classList.remove("err");
}

function applyRailWidth(width) {
  // Cap against the viewport too: a 420px rail on a 900px window starves the
  // main area below its minimums, and the chrome clips silently (no scroll).
  const viewportCap = Math.max(72, Math.round(window.innerWidth * 0.35));
  const clamped = Math.max(72, Math.min(420, viewportCap, Math.round(width)));
  document.body.style.setProperty("--rail-width", `${clamped}px`);
  refreshRailClasses(clamped);
  return clamped;
}

// One source of truth for the collapsed rail: dragging it narrow and the
// window itself being narrow both land on the same body classes, so the
// compact styling lives once in CSS instead of a diverging media-query twin.
const railMedia = window.matchMedia("(max-width: 980px)");

function refreshRailClasses(width) {
  const railWidth = railMedia.matches ? 84
    : (width || parseInt(getComputedStyle(document.body).getPropertyValue("--rail-width"), 10) || 260);
  document.body.classList.toggle("rail-compact", railWidth < 170);
  document.body.classList.toggle("rail-narrow", railWidth < 220);
}

function initRailResizer() {
  const handle = $("railResizer");
  if (!handle) return;
  const saved = Number(localStorage.getItem("pineDesktopRailWidth") || 260);
  applyRailWidth(saved);
  railMedia.addEventListener("change", () => refreshRailClasses());
  window.addEventListener("resize", () => {
    // Re-clamp a wide rail when the window shrinks under it — but never
    // fight an active drag, whose width isn't saved until pointerup.
    if (railResize) return;
    applyRailWidth(Number(localStorage.getItem("pineDesktopRailWidth") || 260));
  });
  handle.addEventListener("pointerdown", (event) => {
    railResize = { pointerId: event.pointerId };
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-rail");
    event.preventDefault();
  });
  handle.addEventListener("pointermove", (event) => {
    if (!railResize || railResize.pointerId !== event.pointerId) return;
    applyRailWidth(event.clientX);
  });
  const stop = (event) => {
    if (!railResize || railResize.pointerId !== event.pointerId) return;
    const width = applyRailWidth(event.clientX);
    localStorage.setItem("pineDesktopRailWidth", String(width));
    document.body.classList.remove("resizing-rail");
    railResize = null;
  };
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
}

/* #982: what the shell's own music player should actually be sitting at.
 *
 * APP VOLUME IS THE MASTER - the level of the whole application - and
 * the three stream sliders are the MIX inside the broadcast. The output
 * of the music player is therefore the master times the music share, and
 * that product is the ONLY thing that should ever be written to the
 * element. Keeping it in one function is what stops the two ideas being
 * confused again. */
function desktopMusicGain() {
  const share = (streamVolumes && Number.isFinite(streamVolumes.music))
    ? streamVolumes.music : 1;
  return Math.max(0, Math.min(1, appVolume * share));
}

function setAppVolume(value, persist = true) {
  const raw = Number(value);
  appVolume = Math.max(0, Math.min(1, Number.isFinite(raw) ? raw : 0.35));
  const player = $("desktopRadioPlayer");
  if (player) {
    player.volume = desktopMusicGain();
    player.muted = desktopMusicGain() <= 0;
  }
  const slider = $("appVolume");
  const label = $("appVolumeValue");
  if (slider && Number(slider.value) !== Math.round(appVolume * 100)) {
    slider.value = String(Math.round(appVolume * 100));
  }
  if (label) label.textContent = `${Math.round(appVolume * 100)}%`;
  if (persist) localStorage.setItem("pineDesktopAppVolume", String(appVolume));
  applyAppVolume();
}

function appVolumeScript(audible = true) {
  return `(() => {
    /* #988: EVERY INJECTION REWRITES THESE; THE HOOKS READ THEM.
     *
     * apply() used to close over the values of the injection that
     * happened to install the observer, and the MutationObserver, the
     * two capture listeners and the one-second interval are installed
     * ONCE behind a guard - so every later injection updated numbers
     * that the persistent hooks never looked at again. The sliders moved
     * and a second later the stale interval put the old level back.
     *
     * They live on window now, rewritten by each injection and read on
     * every apply. */
    window.__pineDesktopVolume = ${JSON.stringify(appVolume)};
    window.__pineDesktopAudible = ${JSON.stringify(audible)};
    window.__pineDesktopStreams = ${JSON.stringify(streamVolumes)};
    /* ...and the rAF latch is cleared, because a hidden or throttled
     * webview can leave it set for ever and every hook becomes a no-op. */
    window.__pineDesktopVolumePending = false;
    /* #997: TWO LINES USED TO SIT HERE AND THEY BROKE ALL OF IT.
     *
     *   window.__pineDesktopVolume = audible ? volume : 0;
     *   window.__pineDesktopAudible = audible;
     *
     * 'volume' and 'audible' were consts at THIS scope until #988 moved
     * them onto window. #988 replaced the declarations and left these two
     * readers behind, so the first of them referenced an identifier that
     * no longer existed anywhere in the injected scope - the 'const
     * volume' inside apply() below is block-scoped to apply and is not
     * it. Every injection therefore threw ReferenceError on line 19,
     * BEFORE apply() ran, before the MutationObserver was installed,
     * before the interval was set.
     *
     * Nothing in any webview has been muted or levelled since. That is
     * the whole of "the audio still comes out of the application when
     * everything is set to the Nabu", and the whole of "the sliders do
     * not do anything" - one dead statement, silently swallowed by the
     * .catch() at the call site (also fixed, see applyAppVolumeToFrame).
     *
     * They are simply gone: the three window writes above already say
     * everything they were trying to say, and apply() reads the audible
     * flag itself and zeroes the level when it is false. */
    const apply = () => {
      const volume = Number(window.__pineDesktopVolume) || 0;
      const audible = !!window.__pineDesktopAudible;
      const streams = window.__pineDesktopStreams || {};
      try {
        localStorage.setItem("pineMusicVolume", String(audible ? volume : 0));
        localStorage.setItem("pineMusicMuted", audible && volume > 0 ? "0" : "1");
      } catch (error) {}
      document.querySelectorAll("audio,video").forEach((node) => {
        // #789: the booth-monitor switch governs LIVE broadcast audio only
        // (elements tagged data-pine-live: the music player + booth voice
        // lines). Tapes from the cache and anything you deliberately press
        // play on stay audible at app volume, always.
        const tag = (node.dataset && node.dataset.pineLive) || "";
        const live = !!tag;
        const nodeAudible = live ? audible : true;
        // #981: a live element is scaled by ITS stream. Anything tagged
        // but unnamed (an older panel writes "1") counts as the booth,
        // which is what every one of them was before.
        const share = live
          ? (streams[tag === "1" ? "voice" : tag] ?? 1)
          : 1;
        const nextVolume = nodeAudible ? volume * share : 0;
        if (Math.abs(node.volume - nextVolume) > 0.001) node.volume = nextVolume;
        const muted = !nodeAudible || nextVolume <= 0;
        if (node.muted !== muted) node.muted = muted;
      });
    };
    const schedule = () => {
      if (window.__pineDesktopVolumePending) return;
      window.__pineDesktopVolumePending = true;
      requestAnimationFrame(() => {
        window.__pineDesktopVolumePending = false;
        apply();
      });
    };
    apply();
    if (!window.__pineDesktopVolumeObserver) {
      window.__pineDesktopVolumeObserver = new MutationObserver(schedule);
      window.__pineDesktopVolumeObserver.observe(document.documentElement, {
        childList: true, subtree: true
      });
      document.addEventListener("play", schedule, true);
      document.addEventListener("loadedmetadata", schedule, true);
      window.__pineDesktopVolumeInterval = setInterval(schedule, 1000);
    }
    return Number(window.__pineDesktopVolume) || 0;
  })();`;
}

/* #980 - THE THREE STREAMS, EACH REDIRECTABLE ON ITS OWN.
 *
 * The Broadcast picker is a preset: it moves music, DJs and replies
 * together. That is the common case and it stays. But the streams are
 * independent on the server - /api/dj/output takes them separately - and
 * there was no way to say "keep the music on the box, bring the DJs
 * here" without editing the routing by hand.
 */
const STREAM_ROUTE_IDS = {
  music: "routeMusic", voice: "routeVoice", reply: "routeReply",
};

/* #981 - A VOLUME PER STREAM.
 *
 * App volume is the master and stays exactly what it was. These are
 * proportions of it, so pulling the music down to a bed under the DJs is
 * one drag and does not touch anything else. The panel tags each live
 * audio element with the stream it is carrying, and the reply feed is
 * re-stamped per clip because the DJs and the replies come down one
 * feed - which is why this could not simply be done by element id. */
const STREAM_VOL_IDS = {
  music: "vol_music", voice: "vol_voice", reply: "vol_reply",
};
let streamVolumes = {music: 1, voice: 1, reply: 1};
try {
  const saved = JSON.parse(localStorage.getItem("pineStreamVolumes") || "null");
  if (saved && typeof saved === "object") {
    ["music", "voice", "reply"].forEach((k) => {
      const v = Number(saved[k]);
      if (Number.isFinite(v) && v >= 0 && v <= 1) streamVolumes[k] = v;
    });
  }
} catch (err) { /* first run */ }

function setStreamVolume(stream, fraction, persist = true) {
  const v = Math.max(0, Math.min(1, Number(fraction) || 0));
  streamVolumes[stream] = v;
  const slider = $(STREAM_VOL_IDS[stream]);
  if (slider && Math.abs(Number(slider.value) / 100 - v) > 0.005) {
    slider.value = Math.round(v * 100);
  }
  const label = slider && slider.parentElement;
  if (label) label.classList.toggle("hushed", v <= 0);
  if (persist) {
    try {
      localStorage.setItem("pineStreamVolumes", JSON.stringify(streamVolumes));
    } catch (err) { /* private mode: it still works this session */ }
  }
  applyAppVolume();
  // #982: the shell's own music player follows the music slider, through
  // the one function that knows what its level should be. It does NOT
  // touch appVolume - the master is the operator's, and nothing in here
  // is allowed to move it.
  try {
    const player = $("desktopRadioPlayer");
    if (player && stream === "music") {
      player.volume = desktopMusicGain();
      player.muted = desktopMusicGain() <= 0;
    }
  } catch (err) { /* the slider still moved */ }
  // #971: ...and when the music is going to the BOX, the slider has to
  // reach the box, or it is a control that visibly does nothing. "The
  // music is broadcasting at full volume from the box when really the
  // volume should be very low coming out of the Nabu device" - measured
  // with this very slider at a quarter. Sent to the server, which sets it
  // on the media player entity before each record; the DJs go to the
  // satellite by announce and are not touched by it.
  if (stream === "music" && persist) sendBoxMusicLevel(v);
}

/* Debounced: this rides an oninput, so a drag would otherwise post on
 * every pixel. The box only needs the level the slider LANDS on. */
let boxLevelTimer = null;
let boxLevelSent = null;

function sendBoxMusicLevel(v) {
  const route = streamRoute("music");
  if (route !== "box" && route !== "both") return;
  /* #1007: the level is still remembered - it is what gets sent if the
   * operator ever hands the station that dial - but with the switch off
   * we do not pretend the slider moved the box. */
  if (!(lastRouting && lastRouting.music_control)) {
    noteRouteOk("record level stored at " + Math.round(Number(v) * 100)
      + "% \u2014 the dial on the device is still what the box plays at");
  }
  if (boxLevelTimer) clearTimeout(boxLevelTimer);
  boxLevelTimer = setTimeout(() => {
    boxLevelTimer = null;
    const level = Math.max(0, Math.min(1, Number(v) || 0));
    if (boxLevelSent !== null && Math.abs(boxLevelSent - level) < 0.005) return;
    boxLevelSent = level;
    api.post("/api/dj/output", {music_level: level})
      .then(() => noteRouteOk("record level on the "
        + (lastRouting && lastRouting.voice_device === "nabu"
           ? "Nabu" : "Pine Box") + " \u2192 " + Math.round(level * 100) + "%"))
      .catch((err) => noteRouteError(err.message));
  }, 400);
}

function initStreamVolumes() {
  Object.keys(STREAM_VOL_IDS).forEach((stream) => {
    const slider = $(STREAM_VOL_IDS[stream]);
    if (!slider || slider.dataset.wired) return;
    slider.dataset.wired = "1";
    slider.value = Math.round((streamVolumes[stream] ?? 1) * 100);
    slider.oninput = (ev) =>
      setStreamVolume(stream, Number(ev.target.value) / 100);
  });
  ["music", "voice", "reply"].forEach(
    (k) => setStreamVolume(k, streamVolumes[k], false));
}

/* Paint the three pickers from what the SERVER says, never from what
 * this app last asked for - the routing is shared between clients and
 * the box can change it underneath us. */
function paintStreamRoutes(routing) {
  if (!routing) return;
  /* #967: "They are being broadcasted to the Nabu. These shouldn't say or
   * even mention Pine box."
   *
   * The three per-stream options are value="box", and "box" here does not
   * mean the pine satellite - it means THE BROADCAST DEVICE, whichever
   * one is selected. The label was hardcoded "Pine Box", so with the
   * device set to Nabu the app offered three pickers all naming a box
   * that was not being broadcast to.
   *
   * (The Broadcast preset above is a different control and is left
   * alone: there, Pine Box and Nabu really are two separate choices.) */
  const deviceName = String(routing.voice_device || "") === "nabu"
    ? "Nabu" : "Pine Box";
  Object.keys(STREAM_ROUTE_IDS).forEach((stream) => {
    const select = $(STREAM_ROUTE_IDS[stream]);
    const opt = select && select.querySelector('option[value="box"]');
    if (opt && opt.textContent !== deviceName) opt.textContent = deviceName;
  });
  const now = {music: routing.music_to, voice: routing.voice_to,
               reply: routing.reply_to};
  Object.keys(STREAM_ROUTE_IDS).forEach((stream) => {
    const select = $(STREAM_ROUTE_IDS[stream]);
    if (!select) return;
    const value = String(now[stream] || "");
    if (value && select.value !== value
        && document.activeElement !== select) {
      select.value = value;
    }
    // Amber when this stream is NOT coming out of the app, so a silent
    // application is legible at a glance instead of being a mystery.
    const label = select.parentElement;
    if (label) {
      label.classList.toggle("away",
        value !== "here" && value !== "both");
    }
  });
}

/* #997: "I need this setup to basically reroute the audio instantly when
 * I change these parameters."
 *
 * applyAppVolume() re-injects the webviews, but the shell's OWN player is
 * only re-evaluated by syncDesktopRadio on the next clock poll - so
 * moving music to the box left the record playing here until the poll
 * came round. Every control that can change where audio goes calls this
 * instead, and the local player is re-gated in the same tick. */
function rerouteAudioNow() {
  applyAppVolume();
  try { pollDesktopRadio(); } catch (err) { /* the poll will catch up */ }
}

async function setStreamRoute(stream, value) {
  const body = {};
  body[stream] = value;
  try {
    await api.post("/api/dj/output", body);
    noteRouteOk(stream + " \u2192 "
      + (value === "here" ? "the app" : value === "box" ? "the Pine Box"
         : value === "both" ? "both" : "off"));
    // The preset picker no longer describes what is going on; say so by
    // re-reading the server rather than guessing a label.
    await refresh();
    rerouteAudioNow();                                          // #997
  } catch (err) {
    noteRouteError(err.message);
  }
}

function initStreamRoutes() {
  Object.keys(STREAM_ROUTE_IDS).forEach((stream) => {
    const select = $(STREAM_ROUTE_IDS[stream]);
    if (!select || select.dataset.wired) return;
    select.dataset.wired = "1";
    select.onchange = (ev) => setStreamRoute(stream, ev.target.value);
  });
}

/* #1007: WHO OWNS THE BOX'S VOLUME KNOB.
 *
 * The station and the physical dial are two writers of one number, and
 * the last writer wins. #971 wrote it before every record; #993 cut that
 * to once per change - but "once per change" is still once per restart,
 * because what we last sent lived in memory. A hand on the dial survived
 * until the next time the service came up.
 *
 * There is no cadence that fixes that, so this decides the OWNER instead.
 * Off - the default now - the station never calls volume_set and the
 * device plays records at whatever its dial says. */
function paintBoxVolumeOwner(routing) {
  const box = document.getElementById("boxVolOwn");
  if (!box) return;
  if (!box.dataset.wired) {
    box.dataset.wired = "1";
    box.onchange = () => {
      const on = !!box.checked;
      api.post("/api/dj/output", {music_control: on})
        .then(() => noteRouteOk(on
          ? "the station may set the Pine Box's volume again"
          : "the Pine Box's own dial owns its volume \u2014 the station "
            + "will not move it"))
        .catch((err) => { noteRouteError(err.message); box.checked = !on; });
    };
  }
  if (document.activeElement === box) return;   // mid-click; leave it be
  box.checked = !!(routing && routing.music_control);
  const label = box.parentElement;
  if (label) {
    label.title = box.checked
      ? "Records are set to the Music slider's level on the box, once per "
        + "change. Turning the dial on the device itself will be undone the "
        + "next time that level changes or the station restarts."
      : "The station never sets the Pine Box's volume. Whatever you set on "
        + "the device is what records play at. The Music slider still "
        + "controls music playing in this app.";
  }
}

/* #979: is the broadcast being sent HERE, to this application? */
let lastRouting = null;                 // #980: what the server last said

function routeIsHere() {
  /* #980: ask the SERVER first. A stream moved on its own - "keep the
   * music on the box, bring the DJs here" - has to make this app audible
   * just as much as the preset does, and the preset would not know. */
  if (lastRouting) {
    const vals = [lastRouting.music_to, lastRouting.voice_to,
                  lastRouting.reply_to];
    if (vals.some((v) => v === "here" || v === "both")) return true;
    if (vals.every((v) => v)) return false;   // the server was explicit
  }
  const route = ROUTES[desiredBroadcast];
  if (!route) return false;
  return route.music === "here" || route.voice === "here"
    || route.reply === "here";
}

function audibleFrame() {
  /* #979: THE MONITOR SWITCH IS FOR LISTENING IN, NOT FOR LISTENING.
   *
   * "Tune booth audio" exists so you can hear the show while it is going
   * out of the BOX - it is a monitor. But it gated the frame's live audio
   * unconditionally, so choosing Application, which routes the whole
   * broadcast to this app, still left the DJs muted until you separately
   * ticked a monitor switch. The app was being asked to monitor itself.
   *
   * When the route sends audio HERE, this app is the broadcast and its
   * frame is audible. The switch keeps its real job: hearing the booth
   * while the show is on the box. */
  if (!boothMonitor && !routeIsHere()) return null;
  /* #988: SWITCHING TABS WAS MUTING THE STATION.
   *
   * This returned activeFrame() - whichever view is on top - so the
   * moment the operator selected Radio or Guide, controlFrame stopped
   * being the audible frame and was injected with audible=false, which
   * is a hard volume=0 / muted=true on the music player AND both DJ
   * elements. Going back to Control restored it. Audio away, audio back,
   * on an action performed constantly: that is the cutting in and out.
   *
   * Audibility is a property of the ROUTE and of which frame carries the
   * broadcast, not of which tab happens to be visible. When the route
   * sends audio here, the control frame is the broadcast and it is
   * audible from any tab. activeFrame() still decides in the monitor
   * case, which is what that switch is actually for. */
  if (routeIsHere()) {
    const carrier = $("controlFrame");
    if (carrier && carrier.src) return carrier;
  }
  return activeFrame() || ($("controlFrame")?.src ? $("controlFrame") : null)
    || ($("radioFrame")?.src ? $("radioFrame") : null);
}

function applyAppVolumeToFrame(frame, audible = frame === audibleFrame()) {
  if (!frame || !frame.src || typeof frame.executeJavaScript !== "function") return;
  try {
    // #789: never hard-mute the whole webview for the monitor switch — that
    // silenced tape playback too. Only a zero app volume mutes everything.
    if (typeof frame.setAudioMuted === "function") frame.setAudioMuted(appVolume <= 0);
    /* #997: A FAILED INJECTION MUST NOT BE SILENT.
     *
     * This was `.catch(() => {})`. The injected script is the ONLY thing
     * that mutes and levels audio inside a webview, so when it started
     * throwing, every route and every slider stopped working and the app
     * said nothing at all - for as long as it took someone to notice by
     * ear. A navigating webview does legitimately reject here, which is
     * what the empty catch was for, so that one stays quiet; anything
     * else reaches the note line the operator can actually see. */
    frame.executeJavaScript(appVolumeScript(audible)).catch((err) => {
      const why = String((err && err.message) || err || "");
      if (/destroyed|navigat|not attached|detached/i.test(why)) return;
      noteRouteError("Audio routing script failed: " + why.slice(0, 120));
      try { console.error("[pine] appVolumeScript failed", err); } catch {}
    });
  } catch {
    /* The webview may still be navigating. dom-ready will apply it. */
  }
}

function applyAppVolume() {
  ["controlFrame", "radioFrame", "guideFrame"].forEach((id) => {
    applyAppVolumeToFrame($(id));
  });
}

function initAppVolume() {
  const savedRaw = localStorage.getItem("pineDesktopAppVolume");
  const saved = savedRaw === null ? 0.35 : Number(savedRaw);
  setAppVolume(Number.isFinite(saved) ? saved : 0.35, false);
  const player = $("desktopRadioPlayer");
  if (player) {
    player.addEventListener("volumechange", () => {
      /* #982: THIS IS WHERE THE MASTER WAS BEING EATEN.
       *
       * The listener exists so that dragging the PLAYER's own volume
       * control moves the app volume with it. It compared against
       * appVolume - but once the music slider existed, the correct
       * setting for this element is appVolume TIMES the music share, and
       * every programmatic write of that product looked to this listener
       * exactly like the operator dragging the player down. It answered
       * by pulling the master down to the product, and the next drag
       * multiplied again: measured spiralling to 1%.
       *
       * Compared against what the element SHOULD be at, a programmatic
       * write is silent here and only a real drag moves the master. */
      const want = desktopMusicGain();
      if (Math.abs(player.volume - want) > 0.01) {
        const share = (streamVolumes && streamVolumes.music > 0)
          ? streamVolumes.music : 1;
        setAppVolume(player.volume / share);
      }
      if (player.muted && desktopMusicGain() > 0) player.muted = false;
    });
  }
  const slider = $("appVolume");
  if (slider) {
    slider.addEventListener("input", (event) => {
      setAppVolume(Number(event.target.value) / 100);
    });
  }
}

function viewUrl(route) {
  return `${config.baseUrl}${route}`;
}

function selectView(name) {
  currentView = name;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === name);
  });
  loadFrames();
  applyAppVolume();
}

function loadFrames() {
  if (!config) return;
  const routeByView = {
    control: ["controlFrame", "/"],
    radio: ["radioFrame", "/radio"],
    guide: ["guideFrame", "/guide/pinebox"]
  };
  const active = routeByView[currentView] || routeByView.control;
  const frame = $(active[0]);
  if (frame && !frame.src) {
    frame.src = viewUrl(active[1]);
    wireFrame(frame);
  }
}

function activeFrame() {
  if (currentView === "control") return $("controlFrame");
  if (currentView === "radio") return $("radioFrame");
  if (currentView === "guide") return $("guideFrame");
  return null;
}

function wireFrame(frame) {
  if (frame.dataset.wired) return;
  frame.dataset.wired = "1";
  frame.addEventListener("dom-ready", () => applyAppVolumeToFrame(frame));
  frame.addEventListener("did-finish-load", () => applyAppVolumeToFrame(frame));
  frame.addEventListener("did-fail-load", (event) => {
    if (event.errorCode !== -3) setText("agentState", event.errorDescription || "load failed");
  });
}

function routeKeyFromState(status) {
  const routing = status && status.routing ? status.routing : {};
  if (routing.voice_device === "nabu" && ["box", "both"].includes(routing.voice_to)) return "nabu";
  if (!routing.voice_device && routing.voice_to === "box" && routing.music_to === "here") return "nabu";
  if (routing.voice_to === "box" && routing.music_to === "box") return "box";
  if (routing.voice_to === "here" && routing.music_to === "here") return "app";
  if (routing.voice_to === "both" || routing.music_to === "both") return "app";
  return routing.voice_to || routing.music_to || "box";
}

function routeLabelFromState(routing) {
  if (!routing) return "unknown";
  // #979: app no longer means "music off" — music here IS the app.
  const music = routing.music_to === "here" || (
    routing.music_to === "off" && desiredBroadcast === "nabu"
  ) ? "app" : routing.music_to;
  const voice = (routing.voice_device === "nabu"
      || (!routing.voice_device && routing.voice_to === "box" && routing.music_to === "here"))
      && ["box", "both"].includes(routing.voice_to)
    ? "nabu" : routing.voice_to;
  return `${voice || "unknown"}/${music || "unknown"}`;
}

function setRouteUi(key, note) {
  const select = $("broadcastTarget");
  const next = ROUTES[key] ? key : desiredBroadcast;
  if (select && ROUTES[next] && document.activeElement !== select && !broadcastChanging) {
    select.value = next;
  }
  setText("routeNote", note || (ROUTES[key] ? ROUTES[key].label : "routing unknown"));
}

function setDesiredBroadcast(key) {
  if (!ROUTES[key]) key = "nabu";
  desiredBroadcast = key;
  localStorage.setItem("pineDesktopBroadcast", key);
  const select = $("broadcastTarget");
  if (select && select.value !== key) select.value = key;
  /* #980: AND RE-GATE THE AUDIO. audibleFrame() is derived from the
   * route, and this is the one place the route ever changes - so it is
   * the one place that can guarantee the gate agrees with it.
   *
   * Without this the app came up silent every single launch:
   * applyDefaultBroadcast() adopts the server's routing at boot (#791,
   * deliberately - the app does not overwrite what you set elsewhere),
   * but it lands AFTER applyAppVolume() has already run against the
   * default route of "nabu". routeIsHere() was false at that moment, the
   * frame was muted, and nothing ever re-applied it. */
  try { applyAppVolume(); } catch (err) { /* the route still changed */ }
}

function setFmUi(on) {
  const sw = $("fmSwitch");
  if (sw && sw.checked !== !!on) sw.checked = !!on;
  document.body.classList.toggle("fm-on", !!on);
}

function embeddedRouteScript(key) {
  const route = EMBEDDED_ROUTES[key] || EMBEDDED_ROUTES.nabu;
  return `(() => {
    const route = ${JSON.stringify(route)};
    Object.entries(route).forEach(([id, value]) => {
      localStorage.setItem(id, value);
      const el = document.getElementById(id);
      if (el && el.value !== value) el.value = value;
    });
    if (typeof djRender === "function" && window.djLastState) {
      window.djLastState.music_to = route.djOutput === "nabu" ? "box" : route.djOutput;
      window.djLastState.voice_to = route.djVoiceOut === "nabu" ? "box" : route.djVoiceOut;
      window.djLastState.reply_to = route.djReplyOut === "nabu" ? "box" : route.djReplyOut;
      window.djLastState.voice_device = route.djVoiceOut === "nabu" || route.djReplyOut === "nabu" ? "nabu" : "pine";
      try { djRender(window.djLastState); } catch (error) {}
    }
    return route;
  })();`;
}

function syncEmbeddedBroadcast(key) {
  ["controlFrame", "radioFrame"].forEach((id) => {
    const frame = $(id);
    if (frame && frame.src && typeof frame.executeJavaScript === "function") {
      frame.executeJavaScript(embeddedRouteScript(key)).catch(() => {});
    }
  });
  applyAppVolume();
}

/* #997: what a single stream is ACTUALLY routed to, right now.
 *
 * The server is the authority - the routing is shared between clients and
 * the streams move independently of the preset - and the preset is only
 * the fallback for before the first status lands. Same precedence
 * routeIsHere() uses; this just answers about one stream instead of
 * "any of them". */
function streamRoute(stream) {
  if (lastRouting) {
    const v = lastRouting[stream + "_to"];
    if (v) return String(v);
  }
  const route = ROUTES[desiredBroadcast];
  return route ? String(route[stream] || "") : "";
}

function desktopPlayerEnabled() {
  /* #979: the shell's own clock-synced player is for routes where the
   * page feed carries NO music - broadcasting to the box, and wanting to
   * hear the record here anyway. Now that Application asks the station
   * for music on the page feed, running this as well would play the
   * record twice, a few hundred milliseconds apart.
   *
   * #997: ...but it read `desiredBroadcast === "nabu"`, which is to say
   * it played music out of this app EXACTLY WHEN the operator had sent
   * the broadcast to the device. "Once I set it to go to the device, I
   * need it to go to the device": choosing the Nabu was the one action
   * guaranteed to start the local player.
   *
   * The preset name is the wrong question twice over - it also ignores
   * the three per-stream pickers entirely, so moving music to the box on
   * its own never stopped this. Ask the MUSIC ROUTE, and let the monitor
   * switch mean here what it already means for the booth:
   *
   *   music is here/both -> the page feed carries the record and the
   *                         webview is playing it; playing it again here
   *                         is the double-play #979 warns about.
   *   music is elsewhere -> silent, unless the operator has asked to
   *                         monitor the broadcast in this app.
   */
  const music = streamRoute("music");
  if (music === "here" || music === "both") return false;
  return boothMonitor;
}

function desktopMusicUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `${config.baseUrl}${url.startsWith("/") ? "" : "/"}${url}`;
}

function syncDesktopRadio(clock) {
  const player = $("desktopRadioPlayer");
  if (!player || !clock || !desktopPlayerEnabled()) {
    if (player) player.pause();
    desktopTrackId = "";
    return;
  }
  if (!clock.on || !clock.playing || !clock.url) {
    player.pause();
    desktopTrackId = "";
    return;
  }
  const age = desktopClockAt ? (Date.now() - desktopClockAt) / 1000 : 0;
  let target = (Number(clock.server_ms || 0) - Number(clock.started_ms || 0)) / 1000 + age;
  if (!Number.isFinite(target) || target < 0) target = 0;
  if (clock.seconds) target = Math.min(target, Number(clock.seconds) - 0.75);
  const nextUrl = desktopMusicUrl(clock.url);
  // #982: the master TIMES the music share - this ran on every poll and
  // would otherwise have wiped the music slider a second after it moved.
  player.volume = desktopMusicGain();
  player.muted = desktopMusicGain() <= 0;
  if (clock.id !== desktopTrackId || player.src !== nextUrl) {
    desktopTrackId = clock.id || "";
    player.src = nextUrl;
    player.currentTime = Math.max(0, target);
    player.playbackRate = 1;
    player.play().then(() => { pendingPlayGesture = false; })
      .catch(() => {
        pendingPlayGesture = true;
        noteRouteError("Click anywhere once to allow app audio");
      });
    return;
  }
  if (player.paused && !player.ended) {
    player.play().then(() => { pendingPlayGesture = false; })
      .catch(() => { pendingPlayGesture = true; });
  }
  // #802: a track playing into a zero volume is silence the user asked
  // to hear — say so, once a minute at most, instead of playing mute.
  if (appVolume <= 0 && Date.now() - mutedNoteAt > 60000) {
    mutedNoteAt = Date.now();
    noteRouteError("App volume is at 0 — slide it up to hear the music");
  }
  const drift = player.currentTime - target;
  if (Math.abs(drift) > 3.5) {
    player.currentTime = Math.max(0, target);
    player.playbackRate = 1;
  } else if (Math.abs(drift) > 0.4) {
    player.playbackRate = drift > 0 ? 0.97 : 1.03;
  } else if (player.playbackRate !== 1) {
    player.playbackRate = 1;
  }
}

async function pollDesktopRadio() {
  if (!config) return;
  try {
    const clock = await api.get(`/api/radio/clock?listener=${desktopListenerId}`);
    desktopClockAt = Date.now();
    syncDesktopRadio(clock);
  } catch {
    const player = $("desktopRadioPlayer");
    if (player) player.pause();
  }
}

function renderChecks(status) {
  const box = $("checks");
  box.innerHTML = "";
  const checks = status.checks || [];
  if (!checks.length) {
    box.innerHTML = "<p class='muted'>No live diagnosis yet.</p>";
    return;
  }
  checks.slice(0, 8).forEach((check) => {
    const okClass = check.ok === true ? "ok" : check.ok === false ? "bad" : "skip";
    const symbol = check.ok === true ? "ok" : check.ok === false ? "!" : "-";
    const row = document.createElement("div");
    row.className = "check";
    row.innerHTML = `<b class="${okClass}">${symbol}</b><strong></strong><span></span>`;
    row.querySelector("strong").textContent = check.name || "check";
    row.querySelector("span").textContent = check.detail || "";
    box.appendChild(row);
  });
}

function renderPipeline(data) {
  const box = $("pipeline");
  const events = (data.events || data.pipeline || []).slice(-5).reverse();
  if (!events.length) {
    box.innerHTML = "<p class='muted'>Pipeline quiet.</p>";
    return;
  }
  box.innerHTML = "";
  events.forEach((event) => {
    const line = document.createElement("div");
    line.textContent = `${event.kind || event.stage || "event"}: ${event.text || event.detail || event.message || ""}`;
    box.appendChild(line);
  });
}

async function refresh() {
  try {
    const health = await fetch(`${config.baseUrl}/healthz`);
    setText("agentState", health.ok ? "online" : "not ready");
    setText("connLine", config.baseUrl);
    // The compact rail hides #connLine — the PB mark's ring carries the
    // connection state instead, so no width ever hides whether we're up.
    document.body.classList.toggle("agent-down", !health.ok);
  } catch {
    setText("agentState", "offline");
    setText("boxState", "unknown");
    setText("routeState", "unknown");
    document.body.classList.add("agent-down");
    return;
  }

  try {
    const status = await api.get("/api/pinebox/status");
    setText("boxState", status.healthy === true ? "healthy" : status.healthy === false ? "needs attention" : "checking");
    pulse.held = ((status.delivery || {}).held ?? pulse.held) || 0;
    setText("routeState", routeLabelFromState(status.routing));
    setText("nowState", status.now_playing ? `${status.now_playing.artist || ""} ${status.now_playing.title || ""}`.trim() : "quiet");
    setText("spokenLine", status.spoken || status.cause || status.diag_error || "status loaded");
    const serverKey = routeKeyFromState(status);
    if (!broadcastChanging && serverKey === desiredBroadcast) {
      setRouteUi(serverKey, routeLabelFromState(status.routing));
    } else {
      setRouteUi(desiredBroadcast, routeLabelFromState(status.routing));
    }
    setFmUi(status.routing && status.routing.on);
    /* #980: remember what the server said and paint the three stream
       pickers from it, then re-gate - a stream moved from anywhere
       (another client, the box, a spoken command) has to reach the
       app's audio, not just a change made in this window. */
    lastRouting = status.routing || null;
    paintBoxVolumeOwner(status.routing);                    // #1007
    paintStreamRoutes(status.routing);
    initStreamRoutes();
    initStreamVolumes();
    applyAppVolume();
    renderChecks(status);
  } catch (err) {
    setText("boxState", err.message);
  }

  try {
    const dj = await api.get("/api/dj/pipeline");
    renderPipeline(dj);
  } catch {
    renderPipeline({});
  }
  applyAppVolume();
}

async function loadConfig() {
  config = await api.readConfig();
  if (!config.apiKey) {
    try {
      const found = await api.discoverKey();
      if (found.saved) config = await api.readConfig();
    } catch (err) {
      appendLog(`[desktop] key discovery failed: ${err.message}\n`);
    }
  }
  $("baseUrlInput").value = config.baseUrl;
  $("apiKeyInput").value = config.apiKey || "";
  $("pythonInput").value = config.python || "";
  $("dataDirInput").value = config.dataDir || "";
  $("modeLaunch").classList.toggle("active", config.mode === "launch");
  $("modeAttach").classList.toggle("active", config.mode === "attach");
  loadFrames();
}

async function saveConfig(patch = {}) {
  const url = $("baseUrlInput").value.trim().replace(/\/$/, "") || "http://127.0.0.1:8096";
  const port = Number(new URL(url).port || 80);
  config = await api.writeConfig({
    baseUrl: url,
    port,
    apiKey: $("apiKeyInput").value.trim(),
    python: $("pythonInput").value.trim(),
    dataDir: $("dataDirInput").value.trim(),
    ...patch
  });
  ["controlFrame", "radioFrame", "guideFrame"].forEach((id) => { $(id).src = ""; });
  loadFrames();
  await refresh();
}

function appendLog(line) {
  const box = $("logBox");
  box.textContent += line;
  box.scrollTop = box.scrollHeight;
  if (document.body.classList.contains("rebuilding")) appendRebuildLog(line);
}

function appendRebuildLog(line) {
  const box = $("rebuildLog");
  if (!box) return;
  box.textContent += line;
  const lines = box.textContent.split(/\r?\n/).slice(-120);
  box.textContent = lines.join("\n");
  box.scrollTop = box.scrollHeight;
}

function setBar(id, pct) {
  const el = $(id);
  if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function updateRebuildProgress(event = {}) {
  rebuildPct = Math.max(rebuildPct, Number(event.pct) || 0);
  if (event.stage) rebuildStageSeen.add(event.stage);
  setText("rebuildStage", `${event.stage || "working"}${event.detail ? ` - ${event.detail}` : ""}`);
  setText("rebuildPct", `${Math.round(rebuildPct)}%`);
  setBar("barSource", Math.min(100, rebuildPct * 3.4));
  setBar("barNpx", rebuildPct < 32 ? 0 : Math.min(100, (rebuildPct - 32) * 3.8));
  setBar("barBackend", rebuildPct < 62 ? 0 : Math.min(100, (rebuildPct - 62) * 3.6));
  setBar("barRoute", rebuildPct < 82 ? 0 : Math.min(100, (rebuildPct - 82) * 5.6));
  appendRebuildLog(`> npx pinebox-reconstitute --stage "${event.stage || "working"}"\n`);
  if (event.detail) appendRebuildLog(`  ${event.detail}\n`);
  renderRebuildProcesses(event.stage || "");
}

function renderRebuildProcesses(activeStage = "") {
  const host = $("rebuildProcesses");
  if (!host) return;
  const names = ["ignition", "collapse", "source sync", "npm install", "npx/electron pack",
                 "python deps", "backend", "routing", "pine support", "visualizer", "handoff", "exit"];
  host.innerHTML = "";
  names.forEach((name) => {
    const chip = document.createElement("span");
    chip.textContent = name;
    chip.className = name === activeStage ? "on" : rebuildStageSeen.has(name) ? "done" : "";
    host.appendChild(chip);
  });
}

function startRebuildAnimation() {
  const canvas = $("rebuildCanvas");
  if (!canvas || rebuildAnimation) return;
  const ctx = canvas.getContext("2d");
  const parts = ["Electron", "Agent", "Nabu", "FM", "Routes", "Audio", "Cache", "UI"];
  const resize = () => {
    canvas.width = Math.max(1, canvas.clientWidth * devicePixelRatio);
    canvas.height = Math.max(1, canvas.clientHeight * devicePixelRatio);
  };
  resize();
  window.addEventListener("resize", resize);
  rebuildParticles = parts.map((label, i) => ({
    label,
    x: Math.random(),
    y: Math.random(),
    tx: 0.5 + Math.cos((i / parts.length) * Math.PI * 2) * 0.18,
    ty: 0.5 + Math.sin((i / parts.length) * Math.PI * 2) * 0.18,
    vx: 0,
    vy: 0,
    phase: Math.random() * Math.PI * 2,
    born: performance.now() + i * 240
  }));
  const plex = Array.from({ length: 46 }, () => ({
    x: Math.random(),
    y: Math.random(),
    vx: (Math.random() - 0.5) * 0.0007,
    vy: (Math.random() - 0.5) * 0.0007
  }));
  const draw = () => {
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#05080d";
    ctx.fillRect(0, 0, w, h);
    plex.forEach((p) => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > 1) p.vx *= -1;
      if (p.y < 0 || p.y > 1) p.vy *= -1;
    });
    for (let i = 0; i < plex.length; i += 1) {
      for (let j = i + 1; j < plex.length; j += 1) {
        const a = plex[i], b = plex[j];
        const dx = (a.x - b.x) * w, dy = (a.y - b.y) * h;
        const d = Math.hypot(dx, dy);
        if (d < 170 * devicePixelRatio) {
          ctx.strokeStyle = `rgba(101,199,218,${0.18 * (1 - d / (170 * devicePixelRatio))})`;
          ctx.beginPath();
          ctx.moveTo(a.x * w, a.y * h);
          ctx.lineTo(b.x * w, b.y * h);
          ctx.stroke();
        }
      }
    }
    const now = performance.now();
    const pull = Math.min(1, rebuildPct / 100);
    rebuildParticles.forEach((p) => {
      const visible = now >= p.born && ((now - p.born) % 5200) < 4700;
      const breathe = Math.sin(now / 900 + p.phase) * 0.035;
      const targetX = p.x * (1 - pull) + (p.tx + breathe) * pull;
      const targetY = p.y * (1 - pull) + (p.ty + Math.cos(now / 1000 + p.phase) * 0.03) * pull;
      p.vx += (targetX - p.x) * 0.015;
      p.vy += (targetY - p.y) * 0.015;
      p.vx *= 0.88; p.vy *= 0.88;
      p.x += p.vx; p.y += p.vy;
      p.visible = visible;
    });
    ctx.strokeStyle = "rgba(84,209,139,.38)";
    ctx.lineWidth = 1.4 * devicePixelRatio;
    ctx.beginPath();
    rebuildParticles.filter((p) => p.visible).forEach((p, i) => {
      const x = p.x * w, y = p.y * h;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
    rebuildParticles.forEach((p) => {
      if (!p.visible) return;
      const x = p.x * w, y = p.y * h;
      ctx.fillStyle = "rgba(8,17,26,.88)";
      ctx.strokeStyle = "#65c7da";
      ctx.lineWidth = devicePixelRatio;
      ctx.beginPath();
      ctx.roundRect(x - 54, y - 18, 108, 36, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#edf3f5";
      ctx.font = `${12 * devicePixelRatio}px Segoe UI, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(p.label, x, y);
    });
    rebuildAnimation = requestAnimationFrame(draw);
  };
  draw();
}

function showRebuildOverlay() {
  rebuildPct = 0;
  rebuildStageSeen = new Set();
  document.body.classList.add("rebuilding");
  $("rebuildOverlay")?.classList.add("active");
  const log = $("rebuildLog");
  if (log) log.textContent = "";
  updateRebuildProgress({ stage: "collapse", pct: 1, detail: "starting full restore sequence" });
  startRebuildAnimation();
  const ticks = [
    "npx electron-builder --dir",
    "rmdir node_modules /s /q",
    "npm install --audit=false",
    "npx pinebox-link doctor",
    "npm run desktop:pack",
    "npx pinebox-route apply nabu/app",
  ];
  let tick = 0;
  rebuildTicker = setInterval(() => {
    appendRebuildLog(`$ ${ticks[tick % ticks.length]}\n`);
    tick += 1;
  }, 1100);
}

function hideRebuildOverlay() {
  document.body.classList.remove("rebuilding");
  $("rebuildOverlay")?.classList.remove("active");
  if (rebuildAnimation) cancelAnimationFrame(rebuildAnimation);
  rebuildAnimation = null;
  if (rebuildTicker) clearInterval(rebuildTicker);
  rebuildTicker = null;
}

async function waitForAgent(ms = 30000) {
  const stop = Date.now() + ms;
  while (Date.now() < stop) {
    try {
      const health = await fetch(`${config.baseUrl}/healthz`);
      if (health.ok) return true;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

async function panicRecover() {
  const button = $("panicBtn");
  const was = button.textContent;
  const key = $("broadcastTarget")?.value || "nabu";
  const route = ROUTES[key] || ROUTES.nabu;
  button.disabled = true;
  button.textContent = "...";
  setText("connLine", "collapsing and rebuilding...");
  showRebuildOverlay();
  selectView("logs");
  if (typeof api.reconstituteDesktop === "function") {
    try {
      const result = await api.reconstituteDesktop();
      rebuildRelaunching = !!(result && result.relaunching);
      return;
    } catch (err) {
      appendLog(`[support] full reconstitution failed: ${err.message}\n`);
      appendLog("[support] falling back to live route/recovery repair\n");
    }
  } else {
    appendLog("[support] reconstitution API not loaded yet; relaunch once after this update\n");
    updateRebuildProgress({ stage: "compatibility", pct: 18, detail: "relaunch once to load the rebuild bridge" });
  }
  setText("connLine", "recovering Pine Box...");
  try {
    try {
      await api.post("/api/dj/output", route);
      setText("routeNote", `${route.label} selected`);
    } catch (err) {
      appendLog(`[recover] route failed: ${err.message}\n`);
    }

    let initialized = null;
    try {
      initialized = await api.post("/api/pinebox/initialize", { speak: key === "box" });
      appendLog(`[recover] initialize: ${initialized.cause || initialized.ok || "done"}\n`);
    } catch (err) {
      appendLog(`[recover] initialize failed: ${err.message}\n`);
    }

    if (!initialized || initialized.ok === false) {
      try {
        const recovered = await api.post("/api/pinebox/recover", { restart: false });
        appendLog(`[recover] link repair: ${(recovered.steps || []).join(" | ")}\n`);
      } catch (err) {
        appendLog(`[recover] link repair failed: ${err.message}\n`);
      }
      try {
        await api.post("/api/pinebox/initialize", { speak: true });
      } catch (err) {
        appendLog(`[recover] second initialize failed: ${err.message}\n`);
      }
    }

    await refresh();
    const frame = activeFrame();
    if (frame) frame.reload();
  } catch (err) {
    appendLog(`[recover] ${err.message}\n`);
    const reachable = await waitForAgent(15000);
    if (!reachable && config.mode === "launch") {
      await api.startBackend();
      await waitForAgent(30000);
      await refresh();
    }
  } finally {
    button.disabled = false;
    button.textContent = was;
    setText("connLine", config.baseUrl);
    if (!rebuildRelaunching) hideRebuildOverlay();
  }
}

async function setBroadcastTarget(key) {
  const route = ROUTES[key];
  if (!route) return;
  broadcastChanging = true;
  setDesiredBroadcast(key);
  setText("routeNote", `switching to ${route.label}...`);
  try {
    await api.post("/api/dj/output", route);
    syncEmbeddedBroadcast(key);
    // #979: "immediately" - the frame's audio gate is derived from the
    // route, so re-apply it now rather than leaving it until the next
    // volume change or reload. Without this, choosing Application was
    // silent until something else happened to nudge it.
    try { applyAppVolume(); } catch (err) { /* the route still changed */ }
    if (key === "box" || key === "nabu") {
      await api.post("/api/pinebox/initialize", { speak: key === "box" });
    }
    noteRouteOk(`${route.label} active`);
    await pollDesktopRadio();
    await refresh();
  } catch (err) {
    noteRouteError(err.message);
  } finally {
    broadcastChanging = false;
  }
}

async function applyDefaultBroadcast() {
  if (defaultBroadcastApplied) return;
  defaultBroadcastApplied = true;
  // #791: the desktop no longer forces its saved preset over the box on
  // boot — the routing YOU set on the page is saved in the agent's settings
  // and survives restarts, so the app ADOPTS what the server says instead
  // of overwriting it. The preset writes only when you change the
  // Broadcast dropdown yourself (setBroadcastTarget).
  try {
    const status = await api.get("/api/pinebox/status");
    const key = routeKeyFromState(status);
    if (ROUTES[key]) setDesiredBroadcast(key);
    noteRouteOk(`${(ROUTES[key] || ROUTES[desiredBroadcast] || ROUTES.nabu).label} — as the box has it`);
  } catch (err) {
    /* server quiet — keep showing the saved selection, write nothing */
  }
}

async function setFm(on) {
  setFmUi(on);
  try {
    await api.post(on ? "/api/dj/start" : "/api/dj/stop", {});
    await pollDesktopRadio();
    await refresh();
  } catch (err) {
    noteRouteError(err.message);
    await refresh();
  }
}

// ---- The 3JS gallery: jump the panel between its three.js experiences.
// Keys mirror the panel's PINE_3JS registry; the click rides the webview
// bridge (pineShow3JS closes whatever scene is up first).
const THREEJS_VIEWS = [
  { key: "mind", icon: "🧠", name: "Dialogue Mind", since: "#472 · #465 · #508",
    systems: "three.min.js · /api/dj/pipeline · /api/speakbox/minds",
    what: "How a line of banter is MADE, live",
    desc: "Six stations — documents, sift, LLM, voice, engineer, on air — with travelling packets animated off the real pipeline feed, a dialogue reel, and eight swappable visual themes." },
  { key: "topology", icon: "🪐", name: "Mind Topology", since: "#786 seeds era",
    systems: "three.module.js · /api/mind/topology",
    what: "The cast as a solar system you can steer",
    desc: "Every DJ, caller and manager as a ringed planet with mood orbs and live directives. Click a seed to read its document, ✕ deletes it from the memory, and a person's title pins them to a source." },
  { key: "graph", icon: "⚙", name: "DJ Plexus", since: "#234",
    systems: "three.min.js · /api/dj/graph",
    what: "The machine behind the pair",
    desc: "The DJ as the central node with every powering system in orbit; documents light up and fire pulses down their edges each time one drives a line. Lines are votable and replayable from the rail." },
  { key: "crystal", icon: "💠", name: "Data Crystal", since: "#350 · #484",
    systems: "three.module.js · /api/dj/crystal",
    what: "Everything they have ever said, crystallised",
    desc: "The whole spoken history as a growing point cloud, one cluster per speaker, placed by phrase embedding so reruns crystallise together. Hover reads a phrase; right-click deletes it from the DJ's memory." },
  { key: "booth", icon: "🎛", name: "DJ Booth", since: "#132",
    systems: "three.module.js · DJ state endpoints",
    what: "The studio itself, as a room",
    desc: "A 3D booth — turntable with platter and tonearm, generated record sleeves in a cover arc — with live transcript, spectrogram scope, transport and a chat line straight to the DJ." },
  { key: "cloud", icon: "☁", name: "Word Cloud", since: "#83 · #97 · #117",
    systems: "three.module.js · /api/wordcloud",
    what: "Every word ever said to the Pine Box",
    desc: "Glowing text sprites on a Fibonacci sphere — size is frequency, colour blends frequency with recency, and the whole thing throbs when something new lands." },
  { key: "sphere", icon: "🔮", name: "Rhetoric Sphere", since: "#610",
    systems: "three.module.js · live chat feed",
    what: "What is being said on air right now, in 3D",
    desc: "The on-air words riding an undulating wireframe icosphere, coloured by which speaker owns each word. Drag to spin, wheel to zoom; rebuilt from the live chat every few seconds." },
  { key: "vectors", icon: "🌳", name: "Vector Tree", since: "#578 · #586",
    systems: "three.module.js · /api/speakbox/vectors",
    what: "The document memory as a living tree",
    desc: "The vector index as a glowing core fed by document nodes — distance is recency, size is swaths and uses, and particle streams assimilate from busy documents into the centre." },
  { key: "stage", icon: "💿", name: "Album Stage", since: "#148 · #170",
    systems: "three.module.js · now-playing state",
    what: "The record that is turning, on a stage",
    desc: "The playing album breathing and drifting on a raked stage with a sweeping sheen; on a track change the old sleeve lies down and rolls out while the next flips up." },
  { key: "remote", icon: "🌐", name: "Remote Plexus", since: "#659 · #660",
    systems: "three.min.js · /api/remote",
    what: "The road out of the house, drawn",
    desc: "The public-broadcast setup stages as glowing sphere nodes over a drifting particle field — the wire between stages lights up as each one lands." },
  { key: "skin", icon: "📼", name: "Device Skin", since: "#144–#147",
    systems: "three.module.js · theme system",
    what: "The hardware behind the page",
    desc: "A full-viewport, audio-reactive render of the themed device — reel-to-reel, keyboard, pad slab — living behind the UI as ambience. Reels spin with the music." },
  { key: "off", icon: "⬛", name: "All off", since: "the sweep",
    systems: "every scene above",
    what: "Take every 3D scene down",
    desc: "Closes every experience in the right order, disarms the auto-reopeners, and leaves the page flat and quiet." },
];

function threejsTip(item, anchor) {
  let tip = $("threejsTip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "threejsTip";
    tip.className = "threejs-tip";
    document.body.appendChild(tip);
  }
  tip.innerHTML = "";
  const h = document.createElement("h4");
  h.textContent = item.icon + " " + item.name;
  const meta = document.createElement("div");
  meta.className = "tip-meta";
  meta.innerHTML =
    "<b>born</b> " + item.since + "<br><b>runs on</b> " + item.systems;
  const what = document.createElement("p");
  what.className = "tip-what";
  what.textContent = item.what;
  const desc = document.createElement("p");
  desc.textContent = item.desc;
  tip.appendChild(h); tip.appendChild(what); tip.appendChild(meta);
  tip.appendChild(desc);
  const at = anchor.getBoundingClientRect();
  tip.style.display = "block";
  tip.style.left = Math.min(at.right + 12, window.innerWidth - 340) + "px";
  tip.style.top = Math.max(8, Math.min(at.top - 10,
    window.innerHeight - tip.offsetHeight - 12)) + "px";
}

function threejsTipHide() {
  const tip = $("threejsTip");
  if (tip) tip.style.display = "none";
}

function initThreejsRail() {
  const btn = $("threejsBtn");
  const list = $("threejsList");
  if (!btn || !list) return;
  THREEJS_VIEWS.forEach((entry) => {
    const key = entry.key;
    const item = document.createElement("button");
    const icon = document.createElement("b");
    icon.textContent = entry.icon;
    const text = document.createElement("span");
    text.textContent = " " + entry.name;
    item.appendChild(icon); item.appendChild(text);
    item.addEventListener("mouseenter", () => threejsTip(entry, item));
    item.addEventListener("mouseleave", threejsTipHide);
    item.addEventListener("click", () => {
      selectView("control");
      const frame = $("controlFrame");
      if (frame && frame.executeJavaScript) {
        frame.executeJavaScript(
          `typeof pineShow3JS === "function" && pineShow3JS(${JSON.stringify(key)})`
        ).catch(() => {});
      }
    });
    list.appendChild(item);
  });
  btn.addEventListener("click", () => {
    const open = list.style.display !== "none";
    list.style.display = open ? "none" : "grid";
    btn.classList.toggle("active", !open);
  });
}
initThreejsRail();

// ---- The heartbeat (Box cell): the DJs' rhetoric reaching the server as
// EKG spikes on a scrolling trace — writing blue, voicing violet, on-air
// green, drops red — with the Spark's CPU breathing in the baseline, heat
// reddening the line, and the task counters growing in real time below.
const pulse = { events: [], cpu: 0, temp: 0, running: 0, held: 0,
                queuedRenders: 0, lastTs: 0 };
const PULSE_COLORS = { model: "#7fd1ff", synth: "#b48cff", air: "#54d18b",
                       drop: "#e46b6b", mining: "#e3be63" };

function initBoxPulse() {
  const canvas = $("boxPulse");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  async function feed() {
    try {
      const p = await api.get("/api/dj/pipeline?since=" + pulse.lastTs);
      (p.events || []).forEach((e) => {
        pulse.lastTs = Math.max(pulse.lastTs, e.ts || 0);
        pulse.events.push({ t: performance.now() / 1000,
                            kind: String(e.kind || "air") });
      });
      if (pulse.events.length > 240) {
        pulse.events.splice(0, pulse.events.length - 240);
      }
      const act = (p.activity || {});
      pulse.queuedRenders = /voicing|writing/.test(act.stage || "") ? 1 : 0;
    } catch (e) {}
    try {
      const d = await api.get("/api/perf");
      pulse.cpu = Number(d.cpu_pct ?? d.cpu ?? 0);
      pulse.temp = Number(d.temp_c ?? 0);
      pulse.running = (d.shell || []).filter((r) => r.ms === null).length;
    } catch (e) {}
    /* #896: the Box cell reports THE PANTRY — how much finished audio is
       stacked and ready to go out. That is the number that says whether
       the station can keep talking through a slow patch; a count of
       running shells never did. */
    try {
      const pd = await api.get("/api/dj/pending");
      pulse.buffered = Number(pd.buffered_seconds || 0);
      pulse.takes = Number(pd.pantry_clips || 0);
      pulse.window = String(pd.window || "");
    } catch (e) {}
    const tasks = $("boxTasks");
    if (tasks) {
      const secs = pulse.buffered || 0;
      const stacked = secs >= 60
        ? (secs / 60).toFixed(1) + " min stacked"
        : Math.round(secs) + "s stacked";
      tasks.textContent =
        "🥫 " + stacked + " · ⏳ "
        + (pulse.queuedRenders ? "rendering" : "idle")
        + " · 🗂 " + pulse.held + " held · "
        + Math.round(pulse.cpu) + "% cpu";
    }
  }
  feed();
  setInterval(feed, 3000);

  const spike = (d, height) => {
    // A narrow EKG lobe: sharp up, sharp down, small rebound.
    const x = d * 9;                      // seconds → lobe-space
    if (x < -1 || x > 1.6) return 0;
    if (x < 0) return height * (1 + x);                  // rising edge
    if (x < 0.5) return height * (1 - x * 2.6);          // overshoot down
    return height * -0.3 * (1.6 - x);                    // rebound tail
  };

  function draw() {
    requestAnimationFrame(draw);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const dpr = devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const now = performance.now() / 1000;
    const speed = 22;                     // px per second of history
    const mid = h * 0.58;
    const hot = pulse.temp > 85;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 1) {
      const at = now - (w - x) / speed;
      let y = mid
        + Math.sin(at * 2.2 + Math.sin(at * 0.7)) * (0.8 + pulse.cpu / 30);
      for (const ev of pulse.events) {
        const s = spike(at - ev.t, h * 0.42);
        if (s) y -= s;
      }
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = hot ? "#e46b6b" : "#65c7da";
    ctx.lineWidth = 1.2;
    ctx.shadowColor = hot ? "#e46b6b" : "#65c7da";
    ctx.shadowBlur = 4;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // Colored footprints under each event, so the KIND reads at a glance.
    for (const ev of pulse.events) {
      const x = w - (now - ev.t) * speed;
      if (x < 0 || x > w) continue;
      ctx.fillStyle = PULSE_COLORS[ev.kind] || "#9fb0bd";
      ctx.globalAlpha = 0.85;
      ctx.fillRect(x - 1, h - 3, 2.5, 3);
      ctx.globalAlpha = 1;
    }
  }
  draw();
}
initBoxPulse();

// ---- The Station drawer: public broadcast, DJ handling and repair at the
// application level. Every value round-trips through the agent, so any
// install on the network reads and writes the same master configuration.
function initStationDrawer() {
  const drawer = $("stationDrawer");
  const btn = $("stationBtn");
  if (!drawer || !btn) return;
  drawer.hidden = false;
  const open = () => { drawer.classList.add("open"); loadStation(); };
  const close = () => drawer.classList.remove("open");
  btn.addEventListener("click", () =>
    drawer.classList.contains("open") ? close() : open());
  $("stationClose").addEventListener("click", close);

  async function loadSpark() {
    // The machine itself: live stats + the services on it, configurable.
    try {
      const [perf, health] = await Promise.all([
        api.get("/api/perf"), fetch(`${config.baseUrl}/health`).then((r) => r.json()),
      ]);
      const lines = [];
      if (perf) {
        if (perf.cpu != null) lines.push(`cpu ${perf.cpu}% · load ${perf.load ?? "—"}`);
        if (perf.ram_used != null) lines.push(`ram ${perf.ram_used}/${perf.ram_total} GB`);
        if (perf.gpu != null) lines.push(`gpu ${perf.gpu}% · vram ${perf.vram_used ?? "—"} GB`);
        if (perf.temp_c != null) lines.push(`temp ${perf.temp_c}°C`);
      }
      Object.entries((health && health.services) || {}).forEach(([k, v]) =>
        lines.push(`${k}: ${v}`));
      if (health && health.model) lines.push(`model: ${health.model}`);
      $("sparkStats").textContent = lines.join("\n") || "no readings";
    } catch (e) { $("sparkStats").textContent = e.message; }
    try {
      const models = await api.get("/api/ollama-models");
      const sel = $("sparkModel");
      // #823: never clobber a dropdown the user has open.
      if (document.activeElement === sel) throw new Error("picker in use");
      sel.innerHTML = "";
      const current = (await api.get("/api/settings")).model || "";
      // Rank by fitness for THIS station's needs — a fast, reliable round
      // writer first, with badges for what each model brings:
      // 🎙 quick banter · 🧠 deep rounds · 👁 sees images · 🛠 tool calls · ⚡ tiny
      const sized = (name) => {
        const m = name.match(/(\d+(?:\.\d+)?)b/i);
        return m ? parseFloat(m[1]) : (/nano|mini|tiny/i.test(name) ? 3 : 8);
      };
      const judge = (name) => {
        const n = name.toLowerCase();
        const b = sized(n);
        const badges = [];
        let score = 0;
        if (b <= 9) { badges.push("🎙"); score += 30; }        // round writer
        if (b >= 12) { badges.push("🧠"); score += 18; }       // deep engine
        if (b <= 4) { badges.push("⚡"); score += 6; }
        if (/llava|vision|moondream|-vl|vl-|gemma[34]|qwen.*vl/.test(n)) {
          badges.push("👁"); score += 14;                      // gallery eyes
        }
        if (/qwen|llama3\.[1-9]|llama4|mistral|nemotron|hermes|command/.test(n)) {
          badges.push("🛠"); score += 10;                      // tool calls
        }
        if (/gemma/.test(n)) score += 22;      // the family this show runs on
        if (/qwen/.test(n)) score += 16;
        if (/nemotron|llama/.test(n)) score += 12;
        if (/embed|whisper|clip|bge|nomic/.test(n)) score -= 80;  // not writers
        if (b > 30) score -= 20;               // too slow for live radio
        return { score, badges };
      };
      const rows = (models.models || []).map((m) => {
        const name = typeof m === "string" ? m : m.name || m.model;
        return { name, ...judge(name) };
      }).sort((a, b) => b.score - a.score);
      rows.forEach((r) => {
        const o = document.createElement("option");
        o.value = r.name;
        o.textContent = (r.badges.join("") || "·") + " " + r.name;
        if (r.name === current) o.selected = true;
        sel.appendChild(o);
      });
      sel.title = "ranked for the station — 🎙 quick banter · 🧠 deep rounds"
        + " · 👁 sees images · 🛠 tool calls · ⚡ tiny";
      sel.onchange = async () => {
        // Immediate: the server switches the live model on this call.
        const stats = $("sparkStats");
        if (stats) stats.textContent = "switching to " + sel.value + "…";
        try {
          await api.post("/api/model", { model: sel.value });
          if (stats) stats.textContent = "model switched: " + sel.value;
          setTimeout(loadSpark, 1200);
        } catch (e) { if (stats) stats.textContent = e.message; }
      };
    } catch (e) {}
  }
  $("sparkRestart").addEventListener("click", async () => {
    $("sparkStats").textContent = "restarting spark-agent…";
    try { await api.post("/api/service/restart", { name: "spark-agent" }); } catch (e) {}
    setTimeout(loadSpark, 8000);
  });
  $("sparkRefresh").addEventListener("click", () => loadSpark());
  // #823: a model pulled in ollama appears here on its own — the list
  // repolls itself instead of loading once at boot and going stale.
  setInterval(() => loadSpark(), 45000);
  // #825: and opening the picker refetches IMMEDIATELY.
  const _sm = $("sparkModel");
  if (_sm) _sm.addEventListener("mousedown", () => {
    if (document.activeElement !== _sm) loadSpark();
  });
  // The Agent status cell is the door to the machine panel.
  const agentCell = $("agentState") && $("agentState").parentElement;
  if (agentCell) {
    agentCell.style.cursor = "pointer";
    agentCell.title = "DGX Spark — statistics and services";
    agentCell.addEventListener("click", () => { open(); loadSpark(); });
  }

  async function loadStation() {
    loadSpark();
    try {
      const net = await api.get("/api/remote?fresh=0");
      const stages = (net.stages || []);
      const done = stages.filter((s) => s.done).length;
      setText("pubStatus", net.public ? "broadcasting beyond the house"
        : `${done}/${stages.length || "?"} stages ready`);
      $("pubStages").textContent = stages.filter((s) => !s.done)
        .map((s) => s.name || s.label || "").filter(Boolean).join(" · ");
    } catch (e) { { const _n = $("pubStatus"); if (_n) _n.textContent = e.message; } }
    try {
      const shares = await api.get("/api/share");
      const live = (shares.links || [])[0];
      if (live) $("pubLink").value = live.url || "";
    } catch (e) {}
    try {
      const s = await api.get("/api/settings");
      const dj = s.dj || {};
      const bind = (id, val, out, fmt) => {
        const el = $(id);
        el.value = val;
        $(out).textContent = fmt ? fmt(val) : val;
        el.oninput = () => { $(out).textContent = fmt ? fmt(el.value) : el.value; };
        el.onchange = () => saveStation();
      };
      bind("stTalk", dj.talk_radio ?? 35, "stTalkV");
      bind("stGap", dj.banter_max_minutes ?? 2.5, "stGapV");
      bind("stCalls", dj.callin_per_hour ?? 4, "stCallsV");
      bind("stDeep", Math.round((dj.deep_rate ?? 0.25) * 100), "stDeepV");
      bind("stVol", Math.round((dj.box_volume ?? 1) * 100), "stVolV");
    } catch (e) { { const _n = $("stSaved"); if (_n) _n.textContent = e.message; } }
  }

  async function saveStation() {
    try {
      const s = await api.get("/api/settings");
      s.dj = {
        ...(s.dj || {}),
        talk_radio: Number($("stTalk").value),
        banter_max_minutes: Number($("stGap").value),
        callin_per_hour: Number($("stCalls").value),
        deep_rate: Number($("stDeep").value) / 100,
        box_volume: Number($("stVol").value) / 100,
      };
      await api.put("/api/settings", s);
      { const _n = $("stSaved"); if (_n) _n.textContent = "saved — every session on the network follows"; }
      setTimeout(() => {
        const _n = $("stSaved");
        if (_n) _n.textContent = "";
      }, 2500);
    } catch (e) { { const _n = $("stSaved"); if (_n) _n.textContent = e.message; } }
  }

  $("pubStart").addEventListener("click", async () => {
    { const _n = $("pubStatus"); if (_n) _n.textContent = "minting the public link…"; }
    try {
      if (!djConfirmedOn()) await api.post("/api/dj/start", {});
      const made = await api.post("/api/share",
        { hours: 168, label: "shared from the desktop", scope: "listen" });
      if (made && made.url) $("pubLink").value = made.url;
      { const _n = $("pubStatus"); if (_n) _n.textContent = "on the air — hand the link to anybody"; }
    } catch (e) { { const _n = $("pubStatus"); if (_n) _n.textContent = e.message; } }
  });
  function djConfirmedOn() {
    const lamp = document.body.classList.contains("fm-on");
    return lamp;
  }
  $("pubCopy").addEventListener("click", async () => {
    const v = $("pubLink").value;
    if (!v) return;
    setText("pubStatus", (await pineCopy(v))
      ? "link copied — paste it anywhere"
      : "could not reach the clipboard — the link is selected, press Ctrl+C");
  });
  $("pubOpen").addEventListener("click", () => {
    const v = $("pubLink").value;
    if (v) api.openExternal(v);
  });
  $("pubRecheck").addEventListener("click", async () => {
    { const _n = $("pubStatus"); if (_n) _n.textContent = "re-checking…"; }
    try { await api.get("/api/remote?fresh=1"); } catch (e) {}
    loadStation();
  });
  $("stInit").addEventListener("click", async () => {
    { const _n = $("stDiagOut"); if (_n) _n.textContent = "initializing — ends with an audible test…"; }
    try {
      const r = await api.post("/api/pinebox/initialize", {});
      $("stDiagOut").textContent = (r.steps || [])
        .map((s) => (s.ok ? "✓ " : "✗ ") + s.name + " — " + s.detail).join("\n");
    } catch (e) { { const _n = $("stDiagOut"); if (_n) _n.textContent = e.message; } }
  });
  $("stRecover").addEventListener("click", async () => {
    { const _n = $("stDiagOut"); if (_n) _n.textContent = "recovering — reloads the speaker link…"; }
    try {
      const r = await api.post("/api/pinebox/recover", { restart: false });
      $("stDiagOut").textContent = (r.steps || []).join("\n");
    } catch (e) { { const _n = $("stDiagOut"); if (_n) _n.textContent = e.message; } }
  });
  $("stDiag").addEventListener("click", async () => {
    { const _n = $("stDiagOut"); if (_n) _n.textContent = "diagnosing…"; }
    try {
      const d = await api.get("/api/pinebox/diagnose");
      $("stDiagOut").textContent = (d.cause || "") + "\n"
        + (d.checks || []).map((c) => (c.ok ? "✓ " : "✗ ") + c.name).join("\n");
    } catch (e) { { const _n = $("stDiagOut"); if (_n) _n.textContent = e.message; } }
  });
}
initStationDrawer();

/* #788: the wake words the box answers to — turn off, add, remove, from the
 * rail. The list lives in the agent's settings so every session shares it. */
function initWakeWords() {
  const btn = $("wakeBtn");
  const pop = $("wakePopup");
  if (!btn || !pop) return;

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  async function readWake() {
    const s = await api.get("/api/settings");
    if (s.voice_out) delete s.voice_out.ha_token;
    return s;
  }

  async function draw() {
    pop.innerHTML = "<div class='muted'>loading…</div>";
    let s;
    try { s = await readWake(); } catch (e) {
      pop.innerHTML = "<div class='muted'>" + esc(e.message) + "</div>";
      return;
    }
    const wake = s.wake || {enabled: true, words: []};
    pop.innerHTML = "";

    const head = document.createElement("label");
    head.className = "wake-head";
    head.innerHTML = "<input type='checkbox' " + (wake.enabled ? "checked" : "")
      + "> <b>Wake words</b> <span class='muted'>the box listens for</span>";
    head.querySelector("input").addEventListener("change", async (ev) => {
      wake.enabled = ev.target.checked;
      s.wake = wake; await api.put("/api/settings", s); draw();
    });
    pop.appendChild(head);

    (wake.words || []).forEach((w, i) => {
      const row = document.createElement("div");
      row.className = "wake-row" + (w.on ? "" : " off");
      row.innerHTML = "<input type='checkbox' " + (w.on ? "checked" : "")
        + " title='hear this wake word or not'>"
        + "<span class='wake-phrase'>“" + esc(w.phrase) + "”</span>"
        + "<span class='wake-route'>→ " + (w.route === "dj" ? "the DJs" : "the LLM")
        + "</span>"
        + "<button class='wake-x' title='remove this wake word'>✕</button>";
      row.querySelector("input").addEventListener("change", async (ev) => {
        wake.words[i].on = ev.target.checked;
        s.wake = wake; await api.put("/api/settings", s); draw();
      });
      row.querySelector(".wake-x").addEventListener("click", async () => {
        wake.words.splice(i, 1);
        s.wake = wake; await api.put("/api/settings", s); draw();
      });
      pop.appendChild(row);
    });

    const add = document.createElement("div");
    add.className = "wake-add";
    add.innerHTML = "<input type='text' placeholder='new wake phrase…'>"
      + "<select><option value='webui'>→ the LLM</option>"
      + "<option value='dj'>→ the DJs</option></select>"
      + "<button>+ add</button>";
    add.querySelector("button").addEventListener("click", async () => {
      const phrase = add.querySelector("input").value.trim();
      if (!phrase) return;
      wake.words.push({phrase, route: add.querySelector("select").value,
                       on: true});
      s.wake = wake; await api.put("/api/settings", s); draw();
    });
    pop.appendChild(add);
  }

  btn.addEventListener("click", () => {
    const open = pop.style.display !== "none";
    pop.style.display = open ? "none" : "block";
    if (!open) draw();
  });
  document.addEventListener("click", (ev) => {
    if (!pop.contains(ev.target) && ev.target !== btn) {
      pop.style.display = "none";
    }
  });
}
initWakeWords();

/* #790: the speaking indicator in the Route cell — animated while a line is
 * actually sounding on the broadcast device, click for the notification
 * history, each entry expandable to its full detail. */
function initRouteSpeak() {
  const cell = $("routeCell");
  const speak = $("routeSpeak");
  const label = $("routeSpeakLabel");
  const pop = $("routeHistory");
  if (!cell || !speak || !pop) return;
  let log = [];

  async function poll() {
    try {
      const s = await api.get("/api/radio");
      log = s.activity_log || [];
      const a = s.activity || {};
      const fresh = a.at && (Date.now() / 1000 - a.at) < 6;
      const working = fresh && a.stage && !/idle|off/i.test(a.stage);
      speak.style.display = working ? "inline-flex" : "none";
      if (working && label) {
        label.textContent = a.stage
          + (a.detail ? " · " + String(a.detail).slice(0, 26) : "");
      }
    } catch { speak.style.display = "none"; }
    setTimeout(poll, 3000);
  }

  function draw() {
    pop.innerHTML = "<h4>What went out — the notification history</h4>";
    if (!log.length) {
      pop.innerHTML += "<div class='rh-snip'>nothing noted yet</div>";
      return;
    }
    log.slice().reverse().forEach((e) => {
      const row = document.createElement("div");
      row.className = "rh-row";
      const when = e.at ? new Date(e.at * 1000).toLocaleTimeString() : "";
      const detail = e.detail || "";
      row.innerHTML = "<div class='rh-line'>"
        + "<span class='rh-when'>" + when + "</span>"
        + "<span class='rh-stage'>" + (e.stage || "") + "</span>"
        + "<span class='rh-snip'>" + detail.replace(/</g, "&lt;") + "</span>"
        + "</div>"
        + "<div class='rh-detail'>" + (detail || "(no detail recorded)")
          .replace(/</g, "&lt;")
        + "\n\n" + (e.stage || "") + " · " + when + "</div>";
      row.addEventListener("click", () => row.classList.toggle("open"));
      pop.appendChild(row);
    });
  }

  cell.addEventListener("click", () => {
    const open = pop.style.display !== "none";
    pop.style.display = open ? "none" : "block";
    if (!open) draw();
  });
  document.addEventListener("click", (ev) => {
    if (!pop.contains(ev.target) && !cell.contains(ev.target)) {
      pop.style.display = "none";
    }
  });
  poll();
}
initRouteSpeak();

/* #836: the radio triage — the Agent cell opens a troubleshooter that
 * reboots whatever it takes: the full tree with the deaf-device rung,
 * plus hand controls for the engines, the device, the stream, the
 * shelf and the voice-director. */
function initTriagePopup() {
  const cell = $("agentCell");
  if (!cell) return;
  cell.style.cursor = "pointer";
  let pop = null;
  let poll = 0;

  const mk = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  function close() {
    if (poll) { clearInterval(poll); poll = 0; }
    if (pop) { pop.remove(); pop = null; }
  }

  function paintSteps(box, steps, verdict, busy) {
    box.textContent = "";
    (steps || []).forEach((s) => {
      const row = mk("div", "tri-step");
      row.appendChild(mk("b", "", s.name));
      row.appendChild(document.createTextNode(" — " + (s.finding || "")));
      if (s.did) row.appendChild(mk("i", "", " → " + s.did));
      box.appendChild(row);
    });
    if (busy) box.appendChild(mk("div", "tri-busy", "⛏ working…"));
    if (verdict && !busy) {
      box.appendChild(mk("div", "tri-verdict", verdict));
    }
    box.scrollTop = box.scrollHeight;
  }

  async function paintEngines(scope) {
    let h = {};
    try { h = await api.get("/api/pinebox/engines"); } catch { h = {}; }
    scope.querySelectorAll(".tri-eng").forEach((row) => {
      const got = h[row.dataset.eng] || {};
      row.querySelector(".tri-dot").classList.toggle("up", !!got.ready);
      row.querySelector(".tri-stat").textContent = got.ready ? "up"
        : String(got.detail || "down").slice(0, 42);
    });
  }

  function open() {
    if (pop) { close(); return; }
    pop = mk("div", "triage-pop");
    const head = mk("div", "tri-head");
    head.appendChild(mk("b", "", "📻 Radio Triage"));
    const x = mk("button", "tri-x", "✕");
    x.onclick = close;
    head.appendChild(x);
    pop.appendChild(head);

    const log = mk("div", "tri-log");
    log.appendChild(mk("div", "tri-busy",
      "The troubleshooter. Repair runs the whole tree — the show, Home "
      + "Assistant, both device entities, the wire, the voice director, "
      + "both engines — then the deaf-device reboot when nothing has "
      + "verified audible, a fresh record, and the held backlog."));
    pop.appendChild(log);

    const acts = mk("div", "tri-acts");
    const repair = mk("button", "tri-primary", "🔧 Repair the radio");
    repair.onclick = async () => {
      repair.disabled = true;
      try {
        const got = await api.post("/api/pinebox/repair", {});
        if (got && got.busy) paintSteps(log, [], "", true);
      } catch (e) {
        paintSteps(log, [], "could not start: " + e.message, false);
        repair.disabled = false;
        return;
      }
      if (poll) clearInterval(poll);
      poll = setInterval(async () => {
        let st = {};
        try { st = await api.get("/api/pinebox/repair"); }
        catch { return; }
        paintSteps(log, st.steps, st.verdict, st.busy);
        if (!st.busy && (st.steps || []).length) {
          clearInterval(poll); poll = 0;
          repair.disabled = false;
          paintEngines(pop);
        }
      }, 2000);
    };
    acts.appendChild(repair);

    const diag = mk("button", "", "🔍 Diagnose only");
    diag.onclick = async () => {
      diag.disabled = true;
      paintSteps(log, [], "", true);
      try {
        const got = await api.post("/api/pinebox/triage", { fix: false });
        paintSteps(log, got.steps, got.verdict, false);
      } catch (e) { paintSteps(log, [], e.message, false); }
      diag.disabled = false;
    };
    acts.appendChild(diag);
    pop.appendChild(acts);

    const rack = mk("div", "tri-rack");
    ["xtts", "f5"].forEach((eng) => {
      const row = mk("div", "tri-eng");
      row.dataset.eng = eng;
      row.appendChild(mk("span", "tri-dot"));
      row.appendChild(mk("b", "", eng.toUpperCase()));
      row.appendChild(mk("span", "tri-stat", "…"));
      [["deploy", "▶ start"], ["terminate", "⏹ stop"],
       ["bounce", "♻ bounce"]].forEach(([act, label]) => {
        const b = mk("button", "", label);
        b.onclick = async () => {
          b.disabled = true;
          try {
            await api.post("/api/pinebox/engine", { engine: eng, act });
          } catch { /* the health refresh shows the truth */ }
          setTimeout(() => {
            paintEngines(rack);
            b.disabled = false;
          }, 3000);
        };
        row.appendChild(b);
      });
      rack.appendChild(row);
    });
    pop.appendChild(rack);

    const util = mk("div", "tri-acts");
    [["device_reboot", "🔁 Reboot the box"],
     ["music_kick", "🎵 Kick the stream"],
     ["drain", "📤 Drain the shelf"],
     ["director_restart", "🚑 Restart director"]].forEach(([act, label]) => {
      const b = mk("button", "", label);
      b.onclick = async () => {
        b.disabled = true;
        try {
          const got = await api.post("/api/pinebox/act", { act });
          paintSteps(log, [{ name: label,
            finding: (got.ok ? "done" : "refused")
              + (got.note ? " — " + got.note : "") }], "", false);
        } catch (e) { paintSteps(log, [], e.message, false); }
        setTimeout(() => { b.disabled = false; }, 4000);
      };
      util.appendChild(b);
    });
    pop.appendChild(util);

    document.body.appendChild(pop);
    paintEngines(rack);
  }

  cell.onclick = open;
}
initTriagePopup();

/* #896 "The Works" — an eagle's eye view of the whole line.
 *
 * The station manufactures a round in four stages and every one of them
 * used to be invisible: the desk WRITES a script, it lands on the
 * RESERVE, the recording room RENDERS its lines into finished takes, the
 * PANTRY holds them, and then they go out. When the air went quiet there
 * was no way to see which stage had stopped. This draws the line as a
 * flow chart with live numbers at every stage, plus who is in the cast,
 * what the scheduler owes the hour, and whatever is actually blocking.
 */
function initWorksPopup() {
  const cell = $("boxCell");
  if (!cell) return;
  cell.style.cursor = "pointer";
  cell.title = "The Works — how the station is manufacturing its dialogue";
  let pop = null;
  let poll = 0;
  let horizonBox = null;       // #896
  const kindOpen = {};         // #893: which kind rows are open
  const kindBody = {};         // ...and their drawers, kept across paints
  let pantryOpen = false;      // #894: the table, expanded
  let pantryRows = null;       // ...and its own drawer

  const mk = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const mins = (s) => (s >= 60 ? (s / 60).toFixed(1) + " min"
                               : Math.round(s) + " s");

  function close() {
    if (poll) { clearInterval(poll); poll = 0; }
    if (pop) { pop.remove(); pop = null; }
    /* #917: and the hour sheet with it. They are one window as far as
     * the operator is concerned — leaving the sheet stranded also meant
     * the next click opened a SECOND sheet on top of the orphan. */
    try {
      const sheet = document.getElementById("worksSched");
      if (sheet) {
        if (sheet.wkTick) clearInterval(sheet.wkTick);
        sheet.remove();
      }
    } catch (e) { /* the flow still closes */ }
  }

  /* #864: every stage OPENS. The owner wants the writing desk's own
   * detail — what it is writing, for whom, under which prompt, and the
   * script that came back — in the same place as the rest of the line.
   * Open/closed lives outside the DOM because paint() rebuilds this
   * whole flow every 2.5 seconds. */
  const wkOpen = {};
  try {
    Object.assign(wkOpen,
      JSON.parse(localStorage.getItem("wkOpen") || "{}") || {});
  } catch (e) { /* first run */ }
  /* #922: the drawer ELEMENTS themselves, kept across rebuilds and
   * re-adopted into each new flow, so an open one is never torn down
   * while it is being read. */
  const wkBody = {};
  /* #883/#887: "stop refreshing these windows when I'm reading them ...
   * it's resetting them and collapsing them", and "this window is still
   * blinking whenever I'm scrolling it, trying to jump to some other
   * window". paint() used to empty the popup and build the whole line
   * again every 2.5 seconds. Emptying a box that scrolls makes the
   * browser clamp its scroll to the top - that IS the jump - and it tore
   * every open drawer out of the document on the way to the new box,
   * taking its scroll and your selection with it.
   *
   * Nothing is emptied any more. The flow, every stage box and every
   * block below it are built ONCE, kept here, and updated in place; text
   * that has not changed is not even rewritten. */
  let wkFlow = null;              // the flow, made once
  const wkBox = {};               // key -> stage box, made once each
  const wkBlocks = {};            // key -> a block under the flow
  const wkSig = {};               // key -> what it last said
  let wkArrowN = 0;

  const wkText = (node, text) => {
    try {
      const s = (text === undefined || text === null) ? "" : String(text);
      if (node && node.textContent !== s) node.textContent = s;
    } catch (e) { /* never worth the window */ }
  };

  /* A rebuild that cannot be avoided: run it, then put the popup's scroll
   * and every surviving inner scroll back exactly where they were. */
  const wkKeep = (fn) => {
    const marks = [];
    let top = 0;
    try {
      top = pop ? pop.scrollTop : 0;
      const kids = pop ? pop.querySelectorAll("*") : [];
      for (let i = 0; i < kids.length; i++) {
        if (kids[i].scrollTop) marks.push([kids[i], kids[i].scrollTop]);
      }
    } catch (e) { /* we can still run the rebuild */ }
    try { if (typeof fn === "function") fn(); } catch (e) { /* keep it */ }
    const put = () => {
      try {
        marks.forEach((m) => {
          if (m[0] && m[0].isConnected && m[0].scrollTop !== m[1]) {
            m[0].scrollTop = m[1];
          }
        });
        if (pop && pop.scrollTop !== top) pop.scrollTop = top;
      } catch (e) { /* drawn either way */ }
    };
    put();
    try { requestAnimationFrame(put); } catch (e) { /* older engines */ }
  };

  /* Rows arrive at the TOP. Give the scroll the pixels they took, so what
   * you are reading stays under your eye instead of sliding down. */
  const wkAnchor = (add) => {
    let was = 0, top = 0, ok = false;
    try { if (pop) { was = pop.scrollHeight; top = pop.scrollTop; ok = true; } }
    catch (e) { ok = false; }
    try { if (typeof add === "function") add(); } catch (e) { /* keep */ }
    try {
      if (ok && top > 0) {
        const grew = pop.scrollHeight - was;
        if (grew) pop.scrollTop = top + grew;
      }
    } catch (e) { /* the list is there either way */ }
  };

  /* The arrows between the stages: made once, in the order paint() asks
   * for them, and left alone from then on. */
  /* #893: one road — its count, a button that commissions another, and
   * a tick onto everything already stacked behind it. */
  function kindRow(host, kind, count) {
    const KNOWN = ["ad", "station_id", "manager", "caller", "gallery",
                   "news", "banter"];
    const row = mk("div", "");
    row.style.cssText = "display:flex;align-items:center;gap:5px;"
      + "font-size:10px;padding:1px 0";
    const okey = "kind:" + kind;
    const tri = mk("button", "", kindOpen[okey] ? "\u25be" : "\u25b8");
    tri.style.cssText = "font-size:9px;padding:0 3px;min-width:16px";
    tri.title = "What is already stacked on this road";
    const drw = kindBody[okey] || mk("div", "");
    kindBody[okey] = drw;
    drw.style.display = kindOpen[okey] ? "block" : "none";
    drw.style.cssText += ";margin:2px 0 4px 18px";
    row.appendChild(tri);
    const nm = mk("span", "", kind);
    nm.style.cssText = "flex:1;min-width:0;color:#9fd8ff";
    row.appendChild(nm);
    const num = mk("b", "", String(count));
    num.style.color = Number(count) > 0 ? "#7ce8a9" : "#e0a35c";
    row.appendChild(num);
    if (KNOWN.indexOf(kind) >= 0) {
      const add = mk("button", "", "+1");
      add.title = "Have another " + kind + " written, recorded and "
        + "stacked. It takes the spare engine slot in a quiet stretch, "
        + "so the live round never waits on it.";
      add.style.cssText = "font-size:9px;padding:0 5px";
      add.onclick = async (ev) => {
        ev.stopPropagation();
        add.disabled = true;
        const was = add.textContent;
        add.textContent = "\u2026";
        try {
          await api.post("/api/pantry/commission", {kind, count: 1});
          add.textContent = "queued";
        } catch (e) { add.textContent = "refused"; }
        setTimeout(() => {
          add.textContent = was;
          add.disabled = false;
        }, 4000);
      };
      row.appendChild(add);
    }
    /* #903: the road's NAME opens it too, not only the triangle. */
    const kindToggle = (ev) => {
      if (ev) ev.stopPropagation();
      kindOpen[okey] = !kindOpen[okey];
      tri.textContent = kindOpen[okey] ? "\u25be" : "\u25b8";
      drw.style.display = kindOpen[okey] ? "block" : "none";
      if (kindOpen[okey]) kindLoad(kind, drw);
    };
    tri.onclick = kindToggle;
    nm.style.cursor = "pointer";
    nm.title = "Click to open or close what is already stacked on this "
      + "road";
    nm.onclick = kindToggle;
    host.appendChild(row);
    host.appendChild(drw);
    if (kindOpen[okey]) kindLoad(kind, drw);
  }

  /* The variants behind one road, in the order the shelf will really
   * consider them, each pushable up or down that order. */
  async function kindLoad(kind, drw) {
    let d = null;
    try {
      d = await api.get("/api/schedule/segment?kind="
                        + encodeURIComponent(kind));
    } catch (e) {
      if (!drw.childNodes.length) drw.textContent = "could not read that";
      return;
    }
    const cands = d.candidates || [];
    const sig = JSON.stringify(cands.map(
      (c) => [c.id, c.priority, c.seconds, c.usable]));
    if (drw.dataset.sig === sig) return;
    drw.dataset.sig = sig;
    drw.textContent = "";
    if (!cands.length) {
      const none = mk("div", "wk-note",
                      "nothing stacked \u2014 use +1 to have one made");
      none.style.cssText = "font-size:9px;opacity:.6";
      drw.appendChild(none);
      return;
    }
    cands.forEach((c, ix) => {
      const it = mk("div", "");
      it.style.cssText = "display:flex;gap:4px;align-items:center;"
        + "font-size:9px;padding:1px 0;opacity:"
        + (c.usable === false ? ".45" : "1");
      const mark = mk("b", "", ix === 0 ? "\u25b6" : String(ix + 1));
      mark.style.color = ix === 0 ? "#9fd8ff" : "#6d8199";
      it.appendChild(mark);
      const t = mk("span", "", String(c.preview || c.title || c.id));
      t.style.cssText = "flex:1;min-width:0;overflow:hidden;"
        + "text-overflow:ellipsis;white-space:nowrap;cursor:pointer";
      /* #902: the same review from the road drawers in The Works. */
      t.title = String(c.preview || "") + "\n\nClick to open this one: "
        + "the recording, every line of the transcript, and your own "
        + "version back through the rooms";
      t.onclick = (ev) => {
        ev.stopPropagation();
        try { wkReviewPopup(kind, c.id); }
        catch (e) { /* the list still works */ }
      };
      it.appendChild(t);
      it.appendChild(mk("span", "wk-note",
                        Math.round(c.seconds || 0) + "s"));
      [["\u25b2", 1, "Push it up the order"],
       ["\u25bc", -1, "Push it down the order"]].forEach(([g, d2, ti]) => {
        const b = mk("button", "wk-ico", g);          // #966
        b.title = ti;
        b.onclick = async (ev) => {
          ev.stopPropagation();
          b.disabled = true;
          try {
            await api.post("/api/schedule/segment/priority",
                           {shelf_id: c.id,
                            priority: (c.priority || 0) + d2});
          } catch (e) {}
          drw.dataset.sig = "";
          kindLoad(kind, drw);
        };
        it.appendChild(b);
      });
      /* #923: and put THIS one through, now. Pins the exact candidate
       * so the shelf hands over the one that was pressed, then
       * interjects a single round — the hour is not moved, so the
       * running order carries on from where it was afterwards. */
      try {
        const ring = mk("button", "wk-ico", "\u260e");     // #966
        ring.title = "Put this one on the air now. The hour is not "
          + "moved \u2014 it carries on from where it was afterwards.";
        ring.onclick = async (ev) => {
          ev.stopPropagation();
          ring.disabled = true;
          const was = ring.textContent;
          ring.textContent = "\u2026";
          try {
            await api.post("/api/shelf/air", {kind: kind, id: c.id});
            ring.textContent = "on air";
          } catch (e2) { ring.textContent = "refused"; }
          setTimeout(() => {
            ring.textContent = was;
            ring.disabled = false;
          }, 5000);
        };
        it.appendChild(ring);
      } catch (e) { /* still listed */ }
      /* #939: play the section, keep it, or open its transcript and
       * take any single line out of it. */
      try { wkTapeBar(it, kind, c.id); } catch (e) { /* still listed */ }
      drw.appendChild(it);
    });
  }

  /* #894: the pantry, as a table. Each take opens onto its own words,
   * and plays and downloads off the one signed URL. */
  function pantryTable(host) {
    const tri = mk("button", "",
                   (pantryOpen ? "\u25be" : "\u25b8") + " EVERY TAKE");
    tri.style.cssText = "font-size:9.5px;padding:1px 6px;margin-top:4px";
    tri.title = "Every take on the shelf, newest first \u2014 what it "
      + "says, who says it, and a play and a keep on each.";
    const drw = pantryRows || mk("div", "");
    pantryRows = drw;
    drw.style.display = pantryOpen ? "block" : "none";
    drw.style.marginTop = "4px";
    tri.onclick = (ev) => {
      ev.stopPropagation();
      pantryOpen = !pantryOpen;
      tri.textContent = (pantryOpen ? "\u25be" : "\u25b8") + " EVERY TAKE";
      drw.style.display = pantryOpen ? "block" : "none";
      if (pantryOpen) pantryLoad(drw);
    };
    host.appendChild(tri);
    host.appendChild(drw);
    if (pantryOpen) pantryLoad(drw);
  }

  async function pantryLoad(drw) {
    let d = null;
    try {
      d = await api.get("/api/pantry/table?most=200");
    } catch (e) {
      if (!drw.childNodes.length) drw.textContent = "the pantry is closed";
      return;
    }
    const rows = d.rows || [];
    const sig = JSON.stringify([d.takes, d.loose, d.unlabelled,
                                rows.length && rows[0].key]);
    if (drw.dataset.sig === sig) return;
    drw.dataset.sig = sig;
    drw.textContent = "";
    const head = mk("div", "wk-note", "");
    head.style.cssText = "font-size:9px;opacity:.7;margin-bottom:3px";
    head.textContent = d.shown + " of " + d.takes + " shown \u00b7 "
      + Math.round((d.seconds || 0) / 60) + " min \u00b7 "
      + d.loose + " loose"
      + (d.unlabelled ? " \u00b7 " + d.unlabelled
                        + " made before the words were kept" : "");
    head.title = "A LOOSE take is one nothing is holding \u2014 the "
      + "render cache doing its job. Those are the ones the horizon "
      + "rolls off first.";
    drw.appendChild(head);
    rows.forEach((r) => drw.appendChild(pantryRow(r)));
  }

  function pantryRow(r) {
    const box = mk("div", "");
    box.style.cssText = "border-bottom:1px solid rgba(255,255,255,.05);"
      + "padding:2px 0";
    const line = mk("div", "");
    line.style.cssText = "display:flex;gap:5px;align-items:center;"
      + "font-size:9.5px";
    const tri = mk("button", "", "\u25b8");
    tri.style.cssText = "font-size:9px;padding:0 3px;min-width:16px";
    line.appendChild(tri);
    const who = mk("span", "", String(r.name || r.who || r.label || ""));
    who.style.cssText = "min-width:52px;color:#9fd8ff";
    line.appendChild(who);
    const txt = mk("span", "",
                   String(r.text || "\u2014 made before the words were "
                                    + "kept \u2014"));
    txt.style.cssText = "flex:1;min-width:0;overflow:hidden;"
      + "text-overflow:ellipsis;white-space:nowrap"
      + (r.text ? "" : ";opacity:.5;font-style:italic");
    line.appendChild(txt);
    const meta = mk("span", "wk-note", "");
    meta.style.cssText = "font-size:9px;opacity:.7;white-space:nowrap";
    meta.textContent = Math.round(r.seconds || 0) + "s"
      + (r.loose ? " \u00b7 loose" : "");
    meta.title = r.held_by ? "held by " + r.held_by
                           : "nothing is holding this take";
    line.appendChild(meta);
    box.appendChild(line);

    const body = mk("div", "");
    body.style.cssText = "display:none;margin:3px 0 4px 22px";
    tri.onclick = (ev) => {
      ev.stopPropagation();
      const on = body.style.display === "none";
      body.style.display = on ? "block" : "none";
      tri.textContent = on ? "\u25be" : "\u25b8";
      if (on && !body.childNodes.length) {
        const full = mk("div", "");
        full.style.cssText = "font-size:9.5px;line-height:1.5;"
          + "white-space:pre-wrap;opacity:.85;margin-bottom:3px";
        full.textContent = String(r.text || "nothing was written down "
          + "beside this take \u2014 it was made before the pantry kept "
          + "the words (#894)");
        body.appendChild(full);
        const facts = mk("div", "wk-note", "");
        facts.style.cssText = "font-size:9px;opacity:.65;margin-bottom:3px";
        facts.textContent = [
          r.voice ? "voice " + r.voice : "",
          r.label || "",
          Math.round(r.seconds || 0) + "s",
          Math.round((r.bytes || 0) / 1024) + " KB",
          r.age_minutes + " min old",
          "used " + (r.used || 0) + "\u00d7",
          r.held_by ? "held by " + r.held_by : "loose",
        ].filter(Boolean).join(" \u00b7 ");
        body.appendChild(facts);
        if (r.media && r.sig) {
          const url = desktopMusicUrl(
            "/media/" + encodeURIComponent(r.media)
            + "?t=" + encodeURIComponent(r.sig));
          const au = mk("audio", "");
          au.controls = true;
          au.preload = "none";
          au.src = url;
          au.style.cssText = "width:100%;height:26px";
          body.appendChild(au);
          const keep = mk("button", "", "\u2b07 keep it");
          keep.title = "Save this take. Same signed URL the player uses.";
          keep.style.cssText = "font-size:9px;padding:1px 6px;margin-top:3px";
          keep.onclick = (e2) => {
            e2.stopPropagation();
            try { api.openExternal(url); } catch (e3) {}
          };
          body.appendChild(keep);
        }
      }
    };
    /* #903: and the take's own words open it, not just the triangle. */
    txt.style.cursor = "pointer";
    txt.onclick = tri.onclick;
    box.appendChild(body);
    return box;
  }

  function wkArrow(host) {
    const k = "arrow" + (++wkArrowN);
    if (!wkBox[k]) {
      wkBox[k] = mk("div", "wk-arrow", "\u25bc");
      /* #933: `host`, not `flow`. The flow is a const declared inside
       * paint(); this function is its SIBLING, so `flow` was never in
       * scope here and every call threw ReferenceError. It is called
       * between the stages, unguarded, and the FIRST call comes
       * straight after stage 1 \u2014 so paint died before drawing anything
       * and the window reported itself unreachable while both of its
       * endpoints were answering 200 with full payloads. Nothing a
       * syntax check can see, which is why #933 also makes the window
       * print the fault instead of blaming the network. */
      host.appendChild(wkBox[k]);
    }
    return wkBox[k];
  }

  /* One block under the flow (the cast, the scheduler, the blockers):
   * made once, and only refilled when what it says has changed - so a
   * repaint does not throw away the sentence you were half way through. */
  function wkBlock(host, key, title, sig, fill_) {
    try {
      let block = wkBlocks[key];
      if (!block) {
        block = mk("div", "wk-block");
        block.wkHead = mk("b", "", title);
        block.appendChild(block.wkHead);
        block.wkIn = mk("div", "");
        block.appendChild(block.wkIn);
        wkBlocks[key] = block;
      }
      if (block.parentElement !== host) host.appendChild(block);
      wkText(block.wkHead, title);
      if (wkSig[key] !== sig) {
        wkSig[key] = sig;
        block.wkIn.textContent = "";
        try { fill_(block.wkIn); } catch (e) { /* leave it empty */ }
      }
      return block;
    } catch (e) { return null; }
  }

  /* #933: one stage failing must not take the other four with it. The
   * fault is shown IN that stage, named, and the flow carries on. */
  function stageSafe() {
    const args = Array.prototype.slice.call(arguments);
    try {
      return stage.apply(null, args);
    } catch (e) {
      try {
        const k = args[6] || ("t:" + args[1]);
        const box = wkBox[k];
        if (box && box.wkNote) {
          box.wkNote.style.display = "";
          box.wkNote.textContent = "this stage could not be drawn — "
            + ((e && e.message) || String(e || ""));
          box.wkNote.title = String((e && e.stack) || "");
        }
      } catch (e2) { /* the other stages still paint */ }
      return null;
    }
  }

  /* #972 - WHO IS IN THE RECORDING ROOM, AS PEOPLE.
   *
   * "put silhouette icons of people here next to each other representing
   * the amount of people in the recording room or who's in the recording
   * room. And then when I hover over it, show me a pop up that tells me
   * who's in a recording room and what lines that they're scheduled to
   * record and what they're recording the lines for."
   *
   * One figure per actor who has lines written and waiting. The one
   * actually at the microphone this instant is lit; the rest are queued.
   * The count IS the row of figures, so "how busy is the room" is
   * answerable without reading a number.
   */
  function wkCastMarks(flow) {
    const cast = (wkFloor && wkFloor.cast) || [];
    let box = wkBox["cast:marks"];
    if (!box) {
      box = mk("div", "");
      box.style.cssText = "display:flex;gap:3px;align-items:center;"
        + "margin:2px 0 0 2px;min-height:14px;font-size:12px;"
        + "cursor:default";
      wkBox["cast:marks"] = box;
      flow.appendChild(box);
    }
    const sig = JSON.stringify(cast.map((c) => [c.who, c.lines, c.rounds,
                                                c.at_the_mic]));
    if (box.wkSig === sig) return;
    box.wkSig = sig;
    box.textContent = "";
    if (!cast.length) {
      const none = mk("span", "wk-note", "nobody is waiting to record");
      none.style.cssText = "font-size:9.5px;opacity:.55";
      box.appendChild(none);
      return;
    }
    cast.forEach((c) => {
      const who = mk("span", "", c.at_the_mic ? "\u{1F399}" : "\u{1F464}");
      who.style.cssText = "line-height:1;filter:grayscale("
        + (c.at_the_mic ? "0" : ".55") + ");opacity:"
        + (c.at_the_mic ? "1" : ".8");
      /* A native title is the popup here on purpose: it cannot be
       * clipped by the flow's scroll box, it survives the 2.5-second
       * repaint, and it costs no layout in a panel where #890 already
       * had to fight for room. */
      who.title = (c.name || c.who) + " \u2014 " + c.lines + " line(s) to "
        + "record across " + c.rounds + " round(s)"
        + (c.at_the_mic ? "\n\u25cf at the microphone now" : "")
        + ((c.roads && c.roads.length)
           ? "\n\nfor: " + c.roads.join(", ") : "")
        + (c.peek ? "\n\nnext up:\n\u201c" + c.peek + "\u201d" : "");
      box.appendChild(who);
    });
    const tally = mk("span", "wk-note", "");
    tally.style.cssText = "font-size:9.5px;opacity:.6;margin-left:4px";
    const lines = cast.reduce((n, c) => n + Number(c.lines || 0), 0);
    tally.textContent = cast.length + " waiting \u00b7 " + lines + " line(s)";
    tally.title = "Hover a figure for who they are and what they owe";
    box.appendChild(tally);
  }

  function stage(flow, title, num, note, cls, frac, key, fill_) {
    /* #883/#887: made once, keyed, and updated in place from then on.
     * The drawer is moved in ONCE - re-adopting it on every paint is what
     * threw away its scroll and your selection ten times a minute. */
    const k = key || ("t:" + title);
    let box = wkBox[k];
    if (!box) {
      box = mk("div", "wk-stage");
      box.wkNum = mk("span", "wk-num", "");
      box.appendChild(box.wkNum);
      box.wkHead = mk("b", "", "");
      box.appendChild(box.wkHead);
      box.wkNote = mk("div", "wk-note", "");
      box.appendChild(box.wkNote);
      box.wkBar = mk("div", "wk-bar");
      box.wkFill = mk("div", "wk-fill");
      box.wkBar.appendChild(box.wkFill);
      box.appendChild(box.wkBar);
      wkBox[k] = box;
      flow.appendChild(box);
    }
    box.wkTitle = title;
    const cn = "wk-stage" + (cls ? " " + cls : "");
    if (box.className !== cn) box.className = cn;
    box.wkNum.style.display = (num == null) ? "none" : "";
    wkText(box.wkNum, num == null ? "" : String(num));
    wkText(box.wkHead,
           (key ? (wkOpen[key] ? "\u25be " : "\u25b8 ") : "") + title);
    box.wkHead.style.cursor = key ? "pointer" : "default";
    box.wkNote.style.display = note ? "" : "none";
    wkText(box.wkNote, note ? String(note) : "");
    if (frac == null) {
      box.wkBar.style.display = "none";
    } else {
      box.wkBar.style.display = "";
      const fc = "wk-fill"
        + (frac >= 0.999 ? " good" : frac < 0.34 ? " warn" : "");
      if (box.wkFill.className !== fc) box.wkFill.className = fc;
      box.wkFill.style.width =
        Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%";
    }
    if (key) {
      let drawer = wkBody[key];
      if (!drawer) { drawer = mk("div", "wk-drawer"); wkBody[key] = drawer; }
      if (drawer.parentElement !== box) box.appendChild(drawer);  // once
      drawer.style.display = wkOpen[key] ? "block" : "none";
      /* The fill is additive and idempotent: it is handed the same
       * element every time and only adds what is new. */
      if (wkOpen[key] && typeof fill_ === "function") {
        try { fill_(drawer); } catch (e) { /* keep what is there */ }
      }
      box.wkHead.onclick = (ev) => {
        ev.stopPropagation();
        wkOpen[key] = !wkOpen[key];
        try { localStorage.setItem("wkOpen", JSON.stringify(wkOpen)); }
        catch (e) { /* private mode */ }
        box.wkHead.textContent =
          (wkOpen[key] ? "\u25be " : "\u25b8 ") + box.wkTitle;
        drawer.style.display = wkOpen[key] ? "block" : "none";
        if (wkOpen[key] && typeof fill_ === "function") {
          try { fill_(drawer); } catch (e) { /* keep what is there */ }
        }
      };
    }
    return box;
  }

  /* One labelled block inside a drawer. */
  function wkPut(drawer, label, text, mono) {
    if (!text) return;
    const h = mk("div", "wk-note", label);
    h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:6px 0 2px;"
      + "opacity:.8";
    drawer.appendChild(h);
    const b = mk("div", "", String(text));
    b.style.cssText = "font-size:10px;line-height:1.5;white-space:pre-wrap;"
      + "max-height:26vh;overflow:auto;padding:5px 7px;border-radius:6px;"
      + "background:#05090f;border:1px solid #24384a"
      + (mono ? ";font-family:ui-monospace,Consolas,monospace" : "");
    drawer.appendChild(b);
  }

  function paint(body, dj, pend) {
    /* #883/#887: NOTHING IS EMPTIED HERE. The flow is built once and
     * every stage is updated in place, so the popup never loses its
     * scroll, never blinks, and never closes the drawer you are reading.
     * The only rebuild left is when the popup itself has been closed and
     * opened again, which is a new body element. */
    wkArrowN = 0;
    if (!wkFlow || wkFlow.parentElement !== body) {
      body.textContent = "";
      wkFlow = mk("div", "wk-flow");
      [wkBox, wkBlocks, wkSig].forEach((m) => {
        Object.keys(m).forEach((key2) => { delete m[key2]; });
      });
      body.appendChild(wkFlow);
    }
    const f = (dj && dj.dialogue_flow) || {};
    const rows = (pend && pend.pending) || [];
    const rendering = rows.filter((r) => r.state === "rendering");
    const ready = rows.filter((r) => r.state === "ready");
    const act = (dj && dj.activity) || {};

    const flow = wkFlow;

    // 1 — the writing desk  (#864: opens onto the paperwork)
    stageSafe(flow, "① the writing desk",
      (dj && dj.model) || "?",
      f.writing ? "writing a round now"
                : "idle — the reserve is at its target",
      f.writing ? "on" : "", null,
      "desk",
      (drawer) => {
        /* #884/#885: ADDITIVE, and every entry folds on its own. Each
         * call the desk makes is added ONCE, newest on top, and nothing
         * already on screen is touched - so entries stack up as they
         * happen and the one you are reading keeps its place, its scroll
         * and its selection. The triangle on an entry folds just that
         * entry away, and the choice is remembered. */
        if (!drawer.dataset.init) {
          drawer.dataset.init = "1";
          drawer.wkSeen = {};
          const tools = mk("div", "");
          tools.style.cssText = "display:flex;gap:6px;align-items:center;"
            + "margin-bottom:4px";
          const hd = mk("div", "wk-note wkDeskHead", "reading the desk\u2026");
          hd.style.cssText = "font-size:10px;flex:1;min-width:0";
          tools.appendChild(hd);
          [["open all", true], ["close all", false]].forEach((pair) => {
            const b = mk("button", "wk-icon", "");
            b.textContent = pair[0];
            b.style.cssText = "position:static;width:auto;height:auto;"
              + "font-size:9px;padding:1px 5px";
            b.onclick = (ev) => {
              ev.stopPropagation();
              try {
                const kids = drawer.querySelectorAll(".wkDeskEntry");
                for (let i = 0; i < kids.length; i++) {
                  wkDeskFold(kids[i], pair[1]);
                }
              } catch (e) { /* each entry still folds by hand */ }
            };
            tools.appendChild(b);
          });
          drawer.appendChild(tools);
          drawer.appendChild(mk("div", "wkDeskList"));
        }
        if (!drawer.wkSeen) drawer.wkSeen = {};
        const head = drawer.querySelector(".wkDeskHead");
        const list = drawer.querySelector(".wkDeskList");
        api.get("/api/writing-desk").then((wd) => {
          const calls = (wd && wd.calls) || [];
          wkText(head, calls.length + " calls held \u00b7 mean "
            + (wd.mean_ms || 0) + " ms, slowest " + (wd.slowest_ms || 0)
            + " ms"
            + (wd.kind_now ? " \u00b7 on a " + wd.kind_now + " segment" : ""));
          if (!list) return;
          const fresh = [];
          calls.slice(0, 12).forEach((c) => {
            const id = "c" + String(c.at || 0) + ":" + String(c.ms || 0);
            if (drawer.wkSeen[id]) return;
            drawer.wkSeen[id] = 1;
            fresh.push([id, c]);
          });
          if (!fresh.length) {
            if (!calls.length && !list.firstChild) {
              wkText(head,
                "nothing yet - each call is recorded as the desk makes it.");
            }
            return;
          }
          // oldest first, so each new one is PREPENDED and the order is
          // newest-at-top without ever moving what is already there
          wkAnchor(() => {
            fresh.reverse().forEach((pair) => {
              list.insertBefore(wkDeskEntry(pair[0], pair[1]),
                                list.firstChild);
            });
            while (list.childNodes.length > 24) {
              const gone = list.lastChild;                 // ages out quietly
              try { wkDeskForget(gone.wkId); }
              catch (e) { /* the row goes either way */ }
              list.removeChild(gone);
            }
          });
        }).catch(() => {
          if (!list || !list.firstChild) {
            wkText(head, "the desk is unreachable");
          }
        });
      });
    wkArrow(flow);

    // 2 — the reserve of written scripts  (#864: opens onto the rounds)
    const target = Number(f.target || 6);
    const have = Number(f.ready || 0);
    wkCastMarks(flow);                                          // #972
    stageSafe(flow, "② the reserve — written scripts",
      have + " / " + target,
      rows.length
        ? rows.length + " round(s) banked and waiting for a slot"
        : "nothing banked — the desk is behind",
      have >= target ? "on" : have === 0 ? "warn" : "",
      target ? have / target : 0,
      "reserve",
      (drawer) => {
        /* #883: this used to append the whole reserve again on every one
         * of the 2.5-second paints - the drawer grew without limit and
         * whatever you were reading marched down the window. It is only
         * rebuilt when the reserve itself has changed, and the scroll is
         * put back when it is. */
        const sig = JSON.stringify((rows || []).map((r) => [r.id, r.state,
          r.turns, r.made, r.chunks, (r.lines || []).length]));
        if (drawer.wkSig === sig && drawer.firstChild) return;
        drawer.wkSig = sig;
        wkKeep(() => {
        drawer.textContent = "";
        if (!rows.length) {
          drawer.appendChild(mk("div", "wk-note", "the shelf is empty"));
          return;
        }
        /* #964: "have all the scripts underneath collapsed and then have a
         * triangle where I can expand each script to read what's going on
         * inside of it."
         *
         * Twelve banked rounds of fourteen turns each poured every line
         * into one drawer, so opening the reserve to see WHAT was banked
         * meant scrolling past everything that already was. Each round
         * folds now, and starts folded, with the head still carrying the
         * numbers so a shut row is still worth reading. Same triangle and
         * the same remembered-open behaviour as the writing desk (#885),
         * with the default the other way round: the desk holds a handful
         * of calls, the reserve holds the whole night. */
        rows.forEach((r, i) => {
          const t = mk("div", "");
          t.style.cssText = "border-left:2px solid "
            + (r.state === "ready" ? "#7ce8a9" : "#3f7fa8")
            + ";padding-left:7px;margin:6px 0";
          const foldKey = "res:" + (r.id || i);
          let open = wkResOpen(foldKey);
          /* #987: "list what these scripts are being written FOR."
           * The reserve listed twelve rounds that all read the same. */
          const label = "#" + (i + 1) + " · " + (r["for"] || "booth rounds")
            + " · " + r.state + " · "
            + r.turns + " turns · " + r.made + "/" + r.chunks + " lines made"
            + (r.seconds ? " · " + Math.round(r.seconds) + "s" : "")
            + (r.edited ? " · edited by hand" : "");
          const nm = mk("div", "");
          nm.style.cssText = "font-size:10.5px;font-weight:700;color:#9fd8ff;"
            + "cursor:pointer;user-select:none";
          nm.textContent = (open ? "▾ " : "▸ ") + label;
          nm.title = "Click to read this round";
          t.appendChild(nm);
          /* A shut row still says something: the first thing anybody says
           * in it is what tells one round from another - #984's lesson,
           * learned on the writing desk. */
          const peek = mk("div", "");
          peek.style.cssText = "font-size:9.5px;line-height:1.45;opacity:.6;"
            + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            + "cursor:pointer;margin-top:1px";
          const lead = (r.lines || [])[0];
          peek.textContent = lead
            ? (lead.name || lead.who) + ": " + String(lead.text || "")
            : "(nothing written in it yet)";
          peek.style.display = open ? "none" : "block";
          t.appendChild(peek);
          const inner = mk("div", "");
          inner.style.display = open ? "block" : "none";
          (r.lines || []).forEach((ln) => {
            const l = mk("div", "");
            l.style.cssText = "font-size:10px;line-height:1.45;margin-top:2px;"
              + "opacity:.75";
            const w = mk("b", "", (ln.name || ln.who) + " ");
            w.style.color = "#7ce8a9";
            l.appendChild(w);
            l.appendChild(document.createTextNode(String(ln.text || "")));
            inner.appendChild(l);
          });
          /* #987/#992: the paperwork, and the pencil. "inspect what the
           * LLM was prompted with, what system prompt we use, what the
           * result was" - and then "edit it... and forward it to the
           * record room with my edits". */
          const tools = mk("div", "");
          tools.style.cssText = "display:flex;gap:5px;margin-top:5px";
          const tbtn = (text, title) => {
            const b = mk("button", "", text);
            b.title = title;
            b.style.cssText = "font-size:9px;padding:2px 7px;border-radius:5px;"
              + "border:1px solid #24384a;background:#0b1520;color:#9fd8ff;"
              + "cursor:pointer";
            return b;
          };
          const paper = tbtn("\u2637 the paperwork",
            "What was sent to the model, what was governing it, "
            + "and what came back");
          paper.onclick = (ev) => { ev.stopPropagation(); wkRoundPaper(r); };
          tools.appendChild(paper);
          const pencil = tbtn("\u270e edit + re-record",
            "Rewrite this round in your own words and send it back "
            + "to the recording room");
          pencil.onclick = (ev) => { ev.stopPropagation(); wkRoundEdit(r); };
          tools.appendChild(pencil);
          inner.appendChild(tools);
          t.appendChild(inner);
          const flip = () => {
            open = !open;
            wkResFold(foldKey, open);
            nm.textContent = (open ? "▾ " : "▸ ") + label;
            inner.style.display = open ? "block" : "none";
            peek.style.display = open ? "none" : "block";
          };
          nm.onclick = flip;
          peek.onclick = flip;
          drawer.appendChild(t);
        });
        });
      });
    wkArrow(flow);

    // 3 — the recording room
    const cur = rendering[0] || null;
    stageSafe(flow, "③ the recording room",
      cur ? (cur.made + " / " + cur.chunks) : (f.window ? "open" : "waiting"),
      f.window
        ? ("building through " + f.window
           + (cur ? " — recording a round's lines" : ""))
        : "the engine is busy with the live round — building is paused",
      cur ? "on" : f.window ? "" : "warn",
      cur && cur.chunks ? cur.made / cur.chunks : null,
      "room",                                            // #876
      (drawer) => {
        /* #883/#887: the waiting note used to be appended on every paint
         * and cleared again a moment later - that flash, twice a second
         * of every five, is the blink. It is said once, and the drawer is
         * only rebuilt when the room has something different to say. */
        if (!drawer.dataset.init) {
          drawer.dataset.init = "1";
          drawer.appendChild(mk("div", "wk-note", "reading the room\u2026"));
        }
        api.get("/api/recording-room").then((rr) => {
          const sig = JSON.stringify([rr && rr.preparing, rr && rr.kinds,
                                      rr && rr.actors]);
          if (drawer.wkSig === sig && drawer.firstChild) return;
          drawer.wkSig = sig;
          wkKeep(() => {
          drawer.textContent = "";
          const p = rr && rr.preparing;
          if (p && p.kind) {
            wkPut(drawer, "IN THE ROOMS NOW",
              (p.stage === "writing" ? "✍ writing room" : "🎙 recording room")
              + " · " + (p.label || p.kind)
              + (p.name ? " · " + p.name : "")
              + (p.voice ? " (" + p.voice + ")" : "")
              + (p.lines ? " · line " + (p.made || 0) + " of " + p.lines : ""));
          }
          const rows2 = (rr && rr.kinds) || [];
          if (rows2.length) {
            /* #959: "put a triangle tick at the front of these that's
             * able to expand showing me more details about each and
             * every task in these sections."  It was one block of
             * pre-formatted text — nine lines of numbers with no way to
             * ask any of them a question. Each road is its own row now,
             * and opening one asks the coordinator what is actually
             * being done about it. */
            const h = mk("div", "wk-note", "THE BOARD, BY CONTENT TYPE");
            h.style.cssText = "font-size:9px;letter-spacing:.05em;"
              + "margin:6px 0 2px;opacity:.8";
            drawer.appendChild(h);
            const board = mk("div", "");
            board.style.cssText = "padding:4px 6px;border-radius:6px;"
              + "background:#05090f;border:1px solid #24384a";
            rows2.forEach((k) => wkBoardRow(board, k));
            drawer.appendChild(board);
          }
          /* #964: "In the recording room offer the last line that was
           * created to be played or downloaded or to have the transcript
           * viewed of it in a single line."  The room described its work
           * in numbers and could not play a second of it. */
          try {
            const last = ((rr && rr.recent) || [])[0] || null;
            if (last) wkLastLine(drawer, last);
          } catch (e) { /* the rest of the room still draws */ }
          /* #959: "list all of the latest lines that have been recorded
           * and download individual lines that have just been recorded.
           * In a list listing the last ten entries that have been
           * captured." Same row as the one above it - play, save, read -
           * so a line found here behaves exactly like the last one made. */
          try {
            const cut = (wkFloor && wkFloor.latest) || [];
            if (cut.length) {
              const lh = mk("div", "wk-note",
                            "THE LAST " + cut.length + " LINES CAPTURED");
              lh.style.cssText = "font-size:9px;letter-spacing:.05em;"
                + "margin:7px 0 2px;opacity:.8";
              drawer.appendChild(lh);
              const list = mk("div", "");
              list.style.cssText = "display:flex;flex-direction:column;gap:3px";
              cut.forEach((t) => {
                try { wkLastLine(list, t, ""); } catch (e) { /* next */ }
              });
              drawer.appendChild(list);
            }
          } catch (e) { /* the rest of the room still draws */ }
          const acts = (rr && rr.actors) || [];
          if (acts.length) {
            wkPut(drawer, "WHO HAS BEEN IN", acts.map((a) =>
              (a.name || a.who) + " — " + a.takes + " takes, "
              + Math.round(a.seconds) + "s"
              + (a.cost ? ", " + a.cost + "× real time" : "")
              + ", " + a.saved_pct + "% off the shelf").join("\n"));
          }
          });
        }).catch(() => {
          if (drawer.wkSig === "gone") return;
          drawer.wkSig = "gone";
          drawer.textContent = "";
          drawer.appendChild(mk("div", "wk-note", "the room is unreachable"));
        });
      });
    wkArrow(flow);

    /* #896: the header dial follows the live figures. */
    try { if (horizonBox && horizonBox.wkShow) horizonBox.wkShow(f); }
    catch (e) { /* the flow still paints */ }

    // 4 — the pantry  (#876: opens onto what is actually on the shelf)
    const secs = Number(f.buffered_seconds || pend.buffered_seconds || 0);
    stageSafe(flow, "④ the pantry — finished audio",
      mins(secs),
      (f.pantry_clips || pend.pantry_clips || 0) + " takes on the shelf"
      + (f.pantry_mb != null
         ? " · " + f.pantry_mb + " MB of " + f.pantry_cap_mb + " MB allowed"
         : "")
      + (ready.length ? " · " + ready.length + " round(s) ready to air" : ""),
      secs > 90 ? "on" : secs < 20 ? "warn" : "",
      Math.min(1, secs / 180),
      "pantry",
      (drawer) => {
        /* #883: this appended itself again on every paint too. */
        const sig = JSON.stringify([f.prepared_by_kind, f.life_hours,
          f.burn_hours, f.hours_ready, f.target_hours, f.window,
          ready.map((r) => [r.turns, Math.round(Number(r.seconds) || 0)])]);
        if (drawer.wkSig === sig && drawer.firstChild) return;
        drawer.wkSig = sig;
        wkKeep(() => {
        drawer.textContent = "";
        const k = f.prepared_by_kind || {};
        const named = Object.keys(k);
        if (named.length) {
          /* #893: each kind COMMISSIONS ANOTHER of itself, and opens
           * onto the variants already stacked behind it. It was seven
           * numbers, four of them zero, and no way to act on that. */
          const lab = mk("div", "wk-note", "PREPARED, BY KIND");
          lab.style.cssText = "font-size:9px;letter-spacing:.05em;"
            + "margin:6px 0 2px;opacity:.8";
          lab.title = "Click a road to have another one written, "
            + "recorded and stacked. Open the tick to see what is "
            + "already behind it.";
          drawer.appendChild(lab);
          const grid = mk("div", "");
          grid.style.cssText = "margin-bottom:6px";
          named.forEach((x) => kindRow(grid, x, k[x]));
          drawer.appendChild(grid);
        }
        wkPut(drawer, "THE SHELF",
          "kept servable for " + (f.life_hours || "?") + " h\n"
          + "burned after " + (f.burn_hours || 24) + " h\n"
          + "hours ready: " + (f.hours_ready || 0)
          + " of " + (f.target_hours || 1)
          + (f.window ? "\nbuilding through " + f.window
                      : "\nthe engine is full — building is paused"));
        if (ready.length) {
          wkPut(drawer, "READY TO AIR", ready.map((r, i) =>
            "#" + (i + 1) + " — " + r.turns + " turns, "
            + Math.round(r.seconds || 0) + "s").join("\n"));
        }
        /* #894: and the pantry ITSELF, listed. */
        pantryTable(drawer);
        });
      });
    wkArrow(flow);

    // 5 — on air
    const now = (dj && dj.now) || {};
    /* #904: speaking_now is an OBJECT — {id, who, kind, text, name, …} —
     * and String()ing it printed "[object Object]" on the glass. Read the
     * line out of it, with the speaker's name in front. */
    const sayingRaw = dj && dj.speaking_now;
    const saying = sayingRaw && typeof sayingRaw === "object"
      ? ((sayingRaw.name ? sayingRaw.name + ": " : "")
         + String(sayingRaw.text || "")).trim()
      : String(sayingRaw || "");
    stageSafe(flow, "⑤ on air",
      dj && dj.speaking ? "talking" : "record",
      saying
        ? saying.slice(0, 160)
        : ((now.artist || "") + " — " + (now.title || "")).slice(0, 120),
      dj && dj.speaking ? "on" : "");
    /* #883: the three blocks under the flow are made once and only
     * refilled when what they say has actually changed. */
    const names = (dj && dj.dj_names) || {};
    wkBlock(body, "cast", "THE CAST",
      JSON.stringify([names, act.stage, act.detail]), (into) => {
        const cg = mk("dl", "wk-grid");
        Object.keys(names).forEach((k) => {
          cg.appendChild(mk("dt", "", k));
          cg.appendChild(mk("dd", "", String(names[k])));
        });
        if (act.stage) {
          cg.appendChild(mk("dt", "", "doing now"));
          cg.appendChild(mk("dd", "",
                            act.stage + " \u00b7 " + (act.detail || "")));
        }
        into.appendChild(cg);
      });

    /* #957: EVERY ROAD THE HOUR OWES, not the two that carry a quota.
     * Only `manager` and `caller` have a per-hour dial, so this readout
     * named those two and said nothing at all about the seven others —
     * including the painting round the operator watched go out with
     * nothing behind it. The others are measured the way the hour
     * measures them: seconds owed against seconds standing by.
     *
     * #958: ...and every row opens. "Anytime they're behind, if I click
     * on that, I want to see a pop up explaining what is being done." */
    const q = f.quota || {};
    const needs = f.hour_needs || {};
    const roads = Object.keys(q).concat(
      Object.keys(needs).filter((k) => !q[k]));
    const sch = wkBlock(body, "sched",
      "THE SCHEDULER \u2014 what the hour owes",
      JSON.stringify([q, needs]),
      (into) => {
        const sg = mk("dl", "wk-grid");
        roads.forEach((k) => {
          const r = q[k];
          const n = needs[k] || {};
          const owed = Number(n.owed || 0);
          const held = Number(n.held || 0);
          const short = Math.max(0, owed - held);
          const late = (r && r.behind) || short > 0;
          const dt = mk("dt", "", k);
          const dd = mk("dd", "", r
            ? (r.aired + " of " + r.target + " this hour"
               + (r.behind ? " \u2014 behind" : " \u2014 on pace")
               + (r.due ? ", due now" : ""))
            : (owed
               ? (Math.round(held) + "s of " + Math.round(owed) + "s owed"
                  + (short > 0 ? " \u2014 " + Math.round(short) + "s short"
                               : " \u2014 covered"))
               : "nothing scheduled for it"));
          [dt, dd].forEach((cell2) => {
            cell2.style.cursor = "pointer";
            cell2.title = "What is being done about " + k
              + " \u2014 click to open";
            cell2.onclick = (ev) => {
              ev.stopPropagation();
              wkRoadPop(k, cell2);
            };
          });
          if (late) dd.style.color = "#f0a35e";
          dd.style.textDecoration = "underline dotted";
          dd.style.textUnderlineOffset = "2px";
          sg.appendChild(dt);
          sg.appendChild(dd);
        });
        into.appendChild(sg);
      });
    if (sch) sch.style.display = roads.length ? "" : "none";

    const stopping = f.blockers || [];
    wkBlock(body, "stops", "WHAT IS HOLDING IT UP",
      JSON.stringify(stopping), (into) => {
        if (!stopping.length) {
          into.appendChild(mk("div", "wk-note",
                              "nothing \u2014 the line is clear"));
          return;
        }
        stopping.forEach((b) => {
          const healthy = /healthy/i.test(b);
          into.appendChild(mk("div", healthy ? "wk-note" : "wk-note wk-stop",
                              (healthy ? "\u2713 " : "\u2022 ") + b));
        });
      });
  }

  /* #933: say WHICH thing broke, and never empty the window to say it. */
  function wkFault(body, where, e) {
    let note = body.wkFault;
    if (!note || note.parentElement !== body) {
      note = mk("div", "wk-note wk-stop");
      note.style.cssText = "font-size:10px;line-height:1.5;margin:4px 0;"
        + "padding:5px 7px;border-radius:6px;border:1px solid #6b2f2f;"
        + "background:rgba(120,40,40,.14);white-space:pre-wrap";
      body.insertBefore(note, body.firstChild);
      body.wkFault = note;
    }
    const msg = (e && (e.message || e.detail)) || String(e || "");
    const frame = String((e && e.stack) || "").split("\n")[1] || "";
    note.textContent = where + " — " + msg
      + (frame ? "\n" + frame.trim() : "");
    note.title = String((e && e.stack) || msg);
  }

  function wkFaultClear(body) {
    if (body.wkFault && body.wkFault.parentElement === body) {
      body.removeChild(body.wkFault);
    }
    body.wkFault = null;
  }

  /* #972/#959: the recording-room floor, refreshed with the rest of the
   * flow and read by two stages - the silhouettes on the reserve and the
   * last-lines list in the recording room. */
  let wkFloor = null;

  async function load(body) {
    let dj = null;
    let pend = null;
    try {
      const got = await Promise.all([
        api.get("/api/dj"),
        api.get("/api/dj/pending"),
        /* #972/#959: who is queued for the recording room, and the last
         * lines out of it. Caught on its own so an older station that
         * does not serve this route still paints everything else. */
        api.get("/api/recording-room/floor?latest=10").catch(() => null),
      ]);
      dj = got[0];
      pend = got[1];
      wkFloor = got[2] || null;
    } catch (e) {
      /* #933: THIS is unreachable — and it says what the transport said
       * rather than leaving the operator to guess between a dead station
       * and a bad key. The window is not emptied: the last good paint is
       * better than a blank box. */
      wkFault(body, "the station did not answer", e);
      return;
    }
    try {
      paint(body, dj, pend);
      wkFaultClear(body);
    } catch (e) {
      /* #933: the endpoints answered and the DRAWING threw. Whatever
       * painted stays on screen; the fault goes at the top with the
       * message and the frame it came from. */
      wkFault(body, "the flow could not be drawn", e);
    }
  }

  /* #896: the horizon control. Reads the live figure, writes it back
   * through the settings document the panel's own sliders use, and says
   * plainly what the number means — because "1.5" on its own reads as a
   * quality setting rather than an hour and a half of cover. */
  function wkHorizon() {
    const wrap = mk("span", "");
    wrap.style.cssText = "display:inline-flex;align-items:center;gap:4px;"
      + "margin-left:10px;font-size:10px;opacity:.85";
    wrap.title = "How far ahead the station writes and records. Material "
      + "past this line is burned oldest-first as new material lands, so "
      + "the buffer rolls rather than grows.";
    wrap.appendChild(mk("span", "wk-sub", "build ahead"));
    const box = mk("select", "");
    box.style.cssText = "font-size:10px;padding:0 2px";
    [["0.5", "30 min"], ["1", "1 hour"], ["1.5", "1\u00bd hours"],
     ["2", "2 hours"], ["3", "3 hours"], ["6", "6 hours"],
     ["12", "12 hours"], ["24", "a day"]].forEach(([v, t]) => {
      const o = mk("option", "", t);
      o.value = v;
      box.appendChild(o);
    });
    const note = mk("span", "wk-sub", "");
    note.style.cssText = "font-size:9.5px;opacity:.7";
    wrap.appendChild(box);
    wrap.appendChild(note);
    wrap.wkShow = (f) => {
      if (box.wkBusy) return;
      const h = Number(f.horizon_hours || f.target_hours || 1.5);
      const want = String(h);
      if (box.value !== want
          && Array.prototype.some.call(box.options,
                                       (o) => o.value === want)) {
        box.value = want;
      }
      const got = Number(f.prepared_hours != null
                         ? f.prepared_hours : f.hours_ready || 0);
      note.textContent = got.toFixed(2) + "h ready"
        + (f.box_depth != null
           ? " \u00b7 digging " + Math.round(Number(f.box_depth) * 100) + "%"
           : "");
      note.title = "How much is genuinely SPOKEN FOR \u2014 prepared "
        + "segments, not cached renders of lines already aired. The "
        + "digging figure is how deep into the speakbox the pair go as "
        + "the queue builds (#895).";
    };
    box.onchange = async () => {
      box.wkBusy = true;
      const was = note.textContent;
      note.textContent = "setting\u2026";
      try {
        const s = await api.get("/api/settings");
        if (s.voice_out) delete s.voice_out.ha_token;
        s.dj = Object.assign({}, s.dj || {},
                             {prepare_hours: Number(box.value)});
        await api.put("/api/settings", s);
        note.textContent = "set";
      } catch (e) { note.textContent = was; }
      setTimeout(() => { box.wkBusy = false; }, 1500);
    };
    horizonBox = wrap;
    return wrap;
  }

  function open() {
    if (pop) { close(); return; }
    pop = mk("div", "works-pop");
    const at = cell.getBoundingClientRect();
    pop.style.left = Math.max(8,
      Math.min(window.innerWidth - 570, at.left - 40)) + "px";
    pop.style.top = (at.bottom + 8) + "px";
    const head = mk("div", "wk-head");
    head.appendChild(mk("b", "", "⚙ The Works"));
    head.appendChild(mk("span", "wk-sub", "how the dialogue gets made"));
    /* #896: HOW FAR AHEAD to build, right here in the header where it
     * was asked for. Everything the preparer does is measured against
     * this line, and material past it rolls off oldest-first. */
    head.appendChild(wkHorizon());
    /* #961: HOW MUCH MEMORY THE CACHING IS TAKING UP, and the P that
     * lets go of it. Asked for right here, beside the horizon dial that
     * decides how much gets made in the first place. */
    try { head.appendChild(wkCacheBadge()); }
    catch (e) { /* the flow still opens */ }
    const x = mk("button", "wk-x", "✕");
    x.onclick = () => {
      try { if (pop.wkBriefPoll) clearInterval(pop.wkBriefPoll); } catch (e) {}
      close();
    };
    head.appendChild(x);
    pop.appendChild(head);
    pop.appendChild(mk("div", "wk-sub",
      "Every round is written, banked, recorded and stacked before it "
      + "goes out. This is where each one is right now."));
    /* #999: THE CONDUCTOR'S LINE. What is wrong with the broadcast right
     * now, in the order that matters, and what is being done about it -
     * so the orchestrator's reading is visible rather than only its
     * actions. Green when the wheels are turning, amber when it is
     * working on something. */
    const brief = mk("div", "");
    brief.style.cssText = "font-size:10px;line-height:1.5;margin:2px 0 6px;"
      + "padding:5px 8px;border-radius:6px;background:#05090f;"
      + "border:1px solid #1b2c3c;cursor:default";
    brief.textContent = "reading the broadcast…";
    pop.appendChild(brief);
    const briefTick = () => {
      api.get("/api/coordinator/brief").then((b) => {
        if (!b) return;
        const bad = (b.worries || []).length;
        brief.style.borderColor = bad ? "#5a4520" : "#1e4433";
        brief.style.color = bad ? "#e0b874" : "#8fd8b4";
        brief.textContent = "♫ the conductor — " + (b.say || "");
        const more = [];
        (b.worries || []).slice(1).forEach((w, i) => {
          more.push("• " + w
                    + ((b.doing || [])[i + 1] ? "  → " + b.doing[i + 1] : ""));
        });
        if ((b.bare || []).length) {
          more.push("nothing behind: " + b.bare.join(", "));
        }
        brief.title = more.length ? more.join(String.fromCharCode(10))
          : "Hover shows anything else it is watching";
      }).catch(() => {});
    };
    briefTick();
    const briefPoll = setInterval(briefTick, 5000);
    pop.wkBriefPoll = briefPoll;
    const body = mk("div", "wk-flow-wrap");
    pop.appendChild(body);
    document.body.appendChild(pop);
    try { wkDraggable(pop); } catch (e) { /* #914 */ }
    load(body);
    poll = setInterval(() => load(body), 2500);
    /* #917: the hour sheet is not a separate window, it is the other
     * half of the director studio. Opened here, and closed with it. */
    try { worksSchedule(pop); } catch (e) { /* the flow still opens */ }
  }

  cell.addEventListener("click", open);
}
try { initWorksPopup(); } catch (e) { /* the desk still works without it */ }

/* #970 — one whole phone call, inside the line's own window.
 *
 * Three things, in the order a person wants them: whether it actually
 * worked, how it flowed, and what was said. Everything is read from
 * /api/dj/call/flow, which derives its stages from the booth log itself
 * — so every box in the chart names the row it came from and nothing
 * here is a reconstruction. */
function dxCallPanel(side, lineId) {
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };
  const box = mk("div", "dxp-sys");
  box.style.cssText = "border-color:#6b4a1f";
  const h = mk("h5", "");
  const dot = mk("span", "", "☎");
  dot.style.color = "#ffb35e";
  h.appendChild(dot);
  h.appendChild(mk("span", "", "the call, end to end"));
  box.appendChild(h);
  const body = mk("div", "");
  box.appendChild(body);
  side.appendChild(box);
  body.appendChild(mk("p", "", "reading the call…"));

  return api.get("/api/dj/call/flow?line=" + encodeURIComponent(lineId))
    .then((d) => {
      body.textContent = "";
      const c = (d && d.counts) || {};
      const sub = mk("p", "",
        (d.name || "somebody") + " · " + (c.caller || 0)
        + " turn(s) from the caller, " + (c.hosts || 0) + " from the booth"
        + (d.seconds ? " · " + Math.round(d.seconds) + "s on air" : ""));
      sub.style.cssText = "opacity:.8";
      body.appendChild(sub);

      /* HOW IT WENT. The faults the server counted, said plainly — this
       * is the "how the customer's experience went" the operator asked
       * for, and it is the difference between a call that worked and one
       * that only looks like a call in the log. */
      const faults = d.faults || [];
      const verdict = mk("div", "");
      verdict.style.cssText = "margin:5px 0;padding:5px 7px;border-radius:6px;"
        + "font-size:10px;line-height:1.55;border:1px solid "
        + (faults.length ? "#6b2f2f;background:#1c0f0f;color:#f0b0b0"
                         : "#2c5f43;background:#0c1a13;color:#9fe0bb");
      if (!faults.length) {
        verdict.textContent = "✓ This one worked as a phone call: the "
          + "caller speaks, the hosts answer them, and it ends.";
      } else {
        verdict.appendChild(mk("b", "", "How this went wrong"));
        faults.forEach((f) => {
          const line = mk("div", "", "• " + f);
          line.style.marginTop = "3px";
          verdict.appendChild(line);
        });
      }
      body.appendChild(verdict);

      /* THE FLOW CHART. A vertical chain — ring, then every turn in the
       * order it aired with the two sides on opposite margins, then how
       * it terminated. The shape itself is the diagnosis: a call with no
       * caller boxes is a call with nobody on the phone. */
      const chart = mk("div", "");
      chart.style.cssText = "margin:6px 0;padding:6px;border-radius:7px;"
        + "background:#05090f;border:1px solid #24384a;max-height:34vh;"
        + "overflow:auto";
      const TONE = {
        ring: ["#65c7da", "☎", "flex-start"],
        caller: ["#ffd7a1", "▸", "flex-start"],
        host: ["#7ce8a9", "◂", "flex-end"],
        hangup: ["#f0a35e", "⏹", "center"],
        never_aired: ["#e88c8c", "✗", "center"],
      };
      (d.flow || []).forEach((step, i) => {
        const spec = TONE[step.stage] || TONE.host;
        if (i) {
          const arrow = mk("div", "", "│");
          arrow.style.cssText = "text-align:center;color:#33465a;"
            + "font-size:9px;line-height:1;margin:1px 0";
          chart.appendChild(arrow);
        }
        const wrap = mk("div", "");
        wrap.style.cssText = "display:flex;justify-content:" + spec[2];
        const node = mk("div", "");
        node.style.cssText = "max-width:82%;font-size:9.5px;line-height:1.5;"
          + "padding:4px 7px;border-radius:6px;background:#0a121b;"
          + "border:1px solid #1d2f3f;border-left:3px solid " + spec[0];
        const lab = mk("div", "", spec[1] + " " + String(step.label || ""));
        lab.style.cssText = "color:" + spec[0] + ";font-weight:600";
        node.appendChild(lab);
        const det = mk("div", "", String(step.detail || "").slice(0, 190)
          + (String(step.detail || "").length > 190 ? "…" : ""));
        det.style.cssText = "color:#c8d6e4;margin-top:1px";
        det.title = String(step.detail || "");
        node.appendChild(det);
        if (step.why) {
          const why = mk("div", "", "why: " + step.why);
          why.style.cssText = "color:#8ba0b5;margin-top:2px;font-size:9px";
          node.appendChild(why);
        }
        wrap.appendChild(node);
        chart.appendChild(wrap);
      });
      if (!(d.flow || []).length) {
        chart.appendChild(mk("div", "",
          "nothing of this call is still in the booth log"));
      }
      body.appendChild(mk("p", "", "THE FLOW"));
      body.appendChild(chart);

      /* THE TRANSCRIPT, both sides, in the order it aired. */
      const turns = d.turns || [];
      if (turns.length) {
        const tw = mk("div", "");
        tw.style.cssText = "margin:6px 0;padding:6px 7px;border-radius:7px;"
          + "background:#05090f;border:1px solid #24384a;max-height:30vh;"
          + "overflow:auto;font-size:10px;line-height:1.6";
        turns.forEach((t) => {
          const row = mk("div", "");
          row.style.marginBottom = "3px";
          const w = mk("b", "", (t.name || (t.mine ? "the caller" : t.who))
                                + ": ");
          w.style.color = t.mine ? "#ffd7a1" : "#7ce8a9";
          row.appendChild(w);
          row.appendChild(document.createTextNode(String(t.text || "")));
          tw.appendChild(row);
        });
        body.appendChild(mk("p", "", "THE TRANSCRIPT"));
        body.appendChild(tw);
      }

      /* AND THE PAPERWORK — the prompts to change if the plan is
       * "handle this customer better next time". */
      const fold = (label, text) => {
        if (!text) return;
        const b = mk("button", "", "▸ " + label);
        b.style.cssText = "display:block;width:100%;text-align:left;"
          + "height:auto;font-size:9.5px;padding:4px 7px;margin-top:4px;"
          + "border-radius:6px";
        const pre = mk("div", "", String(text));
        pre.style.cssText = "display:none;font-size:9px;line-height:1.5;"
          + "white-space:pre-wrap;max-height:28vh;overflow:auto;"
          + "padding:5px 7px;margin-top:3px;border-radius:6px;"
          + "background:#05090f;border:1px solid #24384a;color:#c8d6e4";
        b.onclick = () => {
          const on = pre.style.display === "none";
          pre.style.display = on ? "block" : "none";
          b.textContent = (on ? "▾ " : "▸ ") + label;
        };
        body.appendChild(b);
        body.appendChild(pre);
      };
      const w = d.written || {};
      fold("the system prompt this entry writes with", d.prompt);
      fold("the prompt this call was written from", w.prompt);
      fold("the script that came back", w.script);
      if (w.model) {
        const m = mk("p", "", "written by " + w.model
          + (w.ms ? " in " + Math.round(w.ms) + " ms" : ""));
        m.style.cssText = "opacity:.6;margin-top:4px";
        body.appendChild(m);
      }
    })
    .catch(() => {
      body.textContent = "";
      body.appendChild(mk("p", "",
        "this call is no longer in the booth log"));
    });
}

/* ===================================================================
 * #969 — the right-click menu on a line going past the marquee.
 *
 * Three actions, each one a road the station already has:
 *   transcript — /api/dj/provenance/{id} carries the whole booth row,
 *                the prompt it was written from and how it was made;
 *   download   — /api/booth/clip cuts the exact span of that line out of
 *                the welded round it aired in (X-Pine-Exact says whether
 *                it managed to);
 *   play again — /api/dj/announce in mode "exact" says the words back in
 *                the same seat, which is what "cued for play" means for
 *                a line that has already gone out.
 * =================================================================== */
function dxLineMenu(ev, item) {
  const gone = document.getElementById("dxLineMenu");
  if (gone) gone.remove();
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const menu = mk("div", "works-pop");
  menu.id = "dxLineMenu";
  menu.style.cssText = "position:fixed;z-index:520;width:min(280px,80vw);"
    + "padding:5px;left:" + Math.min(window.innerWidth - 290,
                                     Math.max(6, ev.clientX)) + "px;"
    + "top:" + Math.min(window.innerHeight - 190,
                        Math.max(6, ev.clientY)) + "px";
  menu.onclick = (e) => e.stopPropagation();
  const cap = mk("div", "wk-sub",
    (item.name || "the booth") + " · "
    + String(item.say || "").slice(0, 70)
    + (String(item.say || "").length > 70 ? "…" : ""));
  cap.style.cssText = "font-size:9.5px;line-height:1.45;padding:3px 6px 5px;"
    + "border-bottom:1px solid #24384a;margin-bottom:3px";
  menu.appendChild(cap);
  const note = mk("div", "wk-sub", "");
  note.style.cssText = "font-size:9px;padding:3px 6px 0;min-height:12px";
  const close = () => { menu.remove(); document.removeEventListener("click", away, true); };
  const away = () => close();
  const row = (label, title, fn) => {
    const b = mk("button", "", label);
    b.title = title;
    b.style.cssText = "display:block;width:100%;text-align:left;height:auto;"
      + "font-size:10.5px;padding:5px 8px;margin-bottom:2px;border-radius:6px";
    b.onclick = async (e2) => {
      e2.stopPropagation();
      b.disabled = true;
      try { await fn(b); } catch (err) {
        note.textContent = (err && err.message) || String(err);
      }
      b.disabled = false;
    };
    menu.appendChild(b);
    return b;
  };

  row("📄 transcript", "Read this line in full, and what made it",
      async () => { close(); await dxLineTranscript(item); });

  row("⬇ download this moment",
      "Save the mp3 of the exact moment this line was said",
      async (b) => {
        note.textContent = "cutting…";
        const url = (config.baseUrl || "")
          + "/api/booth/clip?at=" + Math.round(item.at || 0)
          + "&line=" + encodeURIComponent(item.id);
        try {
          await wkSaveBlob(url,
            wkFileName((item.name || "booth") + " "
                       + String(item.say || "").slice(0, 40), "mp3"), b);
          close();
        } catch (e3) {
          note.textContent = "that moment is no longer on the shelf";
        }
      });

  row("▶ play it again",
      "Say this line again, in the same voice, on the air",
      async () => {
        note.textContent = "cueing…";
        await api.post("/api/dj/announce", {
          text: String(item.say || ""),
          mode: "exact",
          who: item.who || "dj",
        });
        note.textContent = "cued — it goes out next";
        setTimeout(close, 1200);
      });

  menu.appendChild(note);
  document.body.appendChild(menu);
  setTimeout(() => document.addEventListener("click", away, true), 0);
}

/* The line in full, with everything the station remembers about it. */
async function dxLineTranscript(item) {
  const gone = document.getElementById("dxLineText");
  if (gone) gone.remove();
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pop = mk("div", "works-pop");
  pop.id = "dxLineText";
  pop.style.cssText = "position:fixed;z-index:520;width:min(560px,92vw);"
    + "max-height:80vh;overflow:auto;left:50%;top:12vh;"
    + "transform:translateX(-50%)";
  pop.onclick = (e) => e.stopPropagation();
  const head = mk("div", "wk-head");
  head.appendChild(mk("b", "", "📄 " + (item.name || "the booth")));
  const sub = mk("span", "wk-sub", "reading the paperwork…");
  head.appendChild(sub);
  const x = mk("button", "wk-x", "✕");
  x.onclick = () => pop.remove();
  head.appendChild(x);
  pop.appendChild(head);
  const said = mk("div", "", String(item.say || ""));
  said.style.cssText = "font-size:12px;line-height:1.65;white-space:pre-wrap;"
    + "margin-top:6px;padding:8px 10px;border-radius:7px;background:#05090f;"
    + "border:1px solid #24384a;color:#dceaf5";
  pop.appendChild(said);
  const more = mk("div", "");
  pop.appendChild(more);
  document.body.appendChild(pop);
  try { wkDraggable(pop); } catch (e) { /* it still opens */ }

  let p = null;
  try {
    p = await api.get("/api/dj/provenance/" + encodeURIComponent(item.id));
  } catch (e) {
    sub.textContent = "that line has scrolled out of the booth — "
      + "its paperwork went with it";
    return;
  }
  const line = (p && p.line) || {};
  sub.textContent = [
    line.kind || item.kind || "",
    line.voice || "",
    line.engine || "",
    line.seconds ? Math.round(line.seconds) + "s" : "",
    item.at ? new Date(item.at * 1000).toLocaleTimeString() : "",
  ].filter(Boolean).join(" · ");
  if (line.text && line.text !== item.say) said.textContent = line.text;
  const put = (label, text) => {
    if (!text) return;
    const h = mk("div", "wk-note", label);
    h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:7px 0 2px;"
      + "opacity:.8";
    more.appendChild(h);
    const b = mk("div", "", String(text));
    b.style.cssText = "font-size:10px;line-height:1.55;white-space:pre-wrap;"
      + "padding:6px 8px;border-radius:6px;background:#05090f;"
      + "border:1px solid #24384a;color:#c8d6e4;max-height:30vh;"
      + "overflow:auto";
    more.appendChild(b);
  };
  const w = (p && p.written) || {};
  put("HOW IT WAS MADE", [
    p.how ? "road: " + p.how : "",
    w.model ? "model: " + w.model : "",
    w.ms ? "took " + Math.round(w.ms) + " ms" : "",
    p.prepared ? "prepared ahead, served off the shelf" : "",
  ].filter(Boolean).join("\n"));
  put("THE SCRIPT IT CAME OUT OF", w.script);
  put("THE PROMPT IT WAS WRITTEN FROM", w.prompt);
  if (Array.isArray(p.material) && p.material.length) {
    put("WHAT IT WAS BUILT ON",
        p.material.map((m) => "• "
          + String((m && (m.text || m.title || m.file)) || m)).join("\n"));
  }
}

/* #966 — which of the two button shapes a label wants.
 *
 * A label with no spaces and at most a couple of glyphs is an ICON and
 * belongs in a square box. Anything with words in it is a text button
 * and gets the pill, whose padding is the same on every side. Emoji are
 * surrogate pairs, so the length test counts CODE POINTS — "☎💬" is two
 * characters, not four. */
function wkBtnClass(label) {
  try {
    const t = String(label == null ? "" : label).trim();
    if (!t) return "wk-ico";
    if (/\s/.test(t)) return "wk-pill";
    return (Array.from(t).length <= 2) ? "wk-ico" : "wk-pill";
  } catch (e) { return "wk-pill"; }
}

/* #965 — one entry's own download, whatever part of the hour it is in.
 *
 * Past  → what actually aired inside this entry's span, welded by the
 *         server out of the booth's own record and kept for two hours.
 * Else  → what is STACKED for it: the prepared segment on the shelf this
 *         entry will draw from, welded by the same coalescer the air
 *         road uses, so what comes down is what would go out.
 * Neither → the button says which of the two is missing, rather than
 *         vanishing and leaving the operator to guess. */
function wkEntryGrab(row, hour, s, gone) {
  const grab = document.createElement("button");
  grab.textContent = "⬇";
  grab.title = gone
    ? "Download what actually went out in this entry"
    : "Download the segment stacked for this entry, welded into one file";
  grab.style.cssText = "position:absolute;right:5px;bottom:5px;"
    + "width:22px;height:22px;padding:0;font-size:10px;line-height:1;"
    + "display:inline-flex;align-items:center;justify-content:center;"
    + "border-radius:6px";
  const settle = (mark, why) => {
    grab.textContent = mark;
    if (why) grab.title = why;
    setTimeout(() => {
      grab.textContent = "⬇";
      grab.disabled = false;
    }, 5000);
  };
  grab.onclick = async (ev) => {
    ev.stopPropagation();
    grab.disabled = true;
    grab.textContent = "…";
    const name = wkFileName(
      hour.date + " " + (s.starts_at || "") + " " + (s.label || s.kind),
      "wav");
    try {
      if (gone) {
        const got = await api.get("/api/schedule/aired?hour="
          + encodeURIComponent(hour.key) + "&slot="
          + encodeURIComponent(s.id));
        if (!got || !got.ready) {
          settle("✗", (got && got.why)
            || (got && got.pruned ? "kept for two hours, then deleted"
                                  : "nothing was kept for this entry"));
          return;
        }
        grab.textContent = "⬇";
        grab.disabled = false;
        await wkSaveBlob(wkMediaUrl(got),
                         wkFileName(hour.date + " " + (s.starts_at || "")
                                    + " " + (s.label || s.kind),
                                    String(got.media || "x.wav")
                                      .split(".").pop()),
                         grab);
        return;
      }
      const seg = await api.get("/api/schedule/segment?kind="
        + encodeURIComponent(s.kind) + "&hour="
        + encodeURIComponent(hour.key) + "&slot="
        + encodeURIComponent(s.id));
      const c = (seg.candidates || [])[0];
      if (!c) {
        settle("✗", CANNOT_SAY[s.kind]
          || "nothing is stacked for this entry yet");
        return;
      }
      const got = await api.get("/api/shelf/bundle?kind="
        + encodeURIComponent(c.kind || s.kind) + "&id="
        + encodeURIComponent(c.id));
      grab.textContent = "⬇";
      grab.disabled = false;
      await wkSaveBlob(wkMediaUrl(got), name, grab);
    } catch (e) {
      settle("✗", (e && e.message) || "that could not be fetched");
    }
  };
  row.appendChild(grab);
  return grab;
}

/* ===================================================================
 * #961 — THE CACHE, MEASURED, AND A BUTTON THAT LETS GO OF IT.
 *
 * "Offer an area here that says how much memory we're taking up with our
 *  caching and allow me to purge the cache at any time with a button ...
 *  I want to be able to just click a P button to purge the cache where
 *  it brings up a purge cache dialogue window and I can choose
 *  specifically what part of the cache I need to purge, which basically
 *  will cause the coordinator to begin queuing up tasks again."
 *
 * Two registers, deliberately kept apart in the dialog because they are
 * different kinds of thing:
 *   the LIVE caches (/api/cache/*) — derived material the station will
 *     simply make again, and the thing whose emptying actually makes the
 *     coordinator start queueing work;
 *   the STORE ROOM (/api/storage/*) — what is on disk, the archive, with
 *     its own protections. Nothing here is deleted without being named.
 * =================================================================== */
function wkMB(bytes) {
  /* #975: a single take is a couple of hundred KB, and rounding it to
     megabytes printed "0 MB" against every row in the table - a column
     of zeroes that says nothing. Scale to the number. */
  const n = Number(bytes) || 0;
  if (n >= (1 << 30)) return (n / (1 << 30)).toFixed(2) + " GB";
  if (n >= 10 * (1 << 20)) return Math.round(n / (1 << 20)) + " MB";
  if (n >= (1 << 20)) return (n / (1 << 20)).toFixed(1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n ? n + " B" : "—";
}

function wkCacheBadge() {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;align-items:center;gap:5px;"
    + "margin-left:6px";
  const say = document.createElement("span");
  say.className = "wk-sub";
  say.textContent = "cache —";
  say.style.whiteSpace = "nowrap";
  wrap.appendChild(say);
  const p = document.createElement("button");
  p.textContent = "P";
  p.title = "Purge the cache — choose exactly what to let go of";
  p.style.cssText = "width:20px;height:20px;padding:0;flex:0 0 auto;"
    + "display:inline-flex;align-items:center;justify-content:center;"
    + "border:1px solid #24384a;border-radius:6px;background:#0b1520;"
    + "color:#ffb35e;font-size:11px;font-weight:700;line-height:1;"
    + "cursor:pointer";
  p.onclick = (ev) => { ev.stopPropagation(); wkPurgePop(p); };
  wrap.appendChild(p);
  const draw = async () => {
    try {
      const c = await api.get("/api/cache/state");
      const used = Number(c.bytes || 0);
      const cap = Number(c.cap_bytes || 0);
      say.textContent = "cache " + wkMB(used)
        + (cap ? " of " + wkMB(cap) : "");
      say.title = (c.areas || []).map((a) =>
        a.label + " — " + (a.rows || 0) + " row(s)"
        + (a.bytes ? ", " + wkMB(a.bytes) : "")
        + (a.seconds ? ", " + Math.round(a.seconds) + "s of audio" : ""))
        .join("\n");
      say.style.color = (cap && used > cap * 0.85) ? "#f0a35e" : "";
    } catch (e) { say.textContent = "cache —"; }
  };
  draw();
  /* The badge is appended by the caller, so it is not in the document
     yet on that first draw - the liveness check belongs on the TICK, not
     on the draw, or the first call clears an interval that does not
     exist yet and throws before it can read anything. */
  const tick = setInterval(() => {
    if (!wrap.isConnected) { clearInterval(tick); return; }
    draw();
  }, 10000);
  return wrap;
}

function wkPurgePop(anchor) {
  const gone = document.getElementById("wkPurgePop");
  if (gone) { gone.remove(); return; }
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pop = mk("div", "works-pop");
  pop.id = "wkPurgePop";
  pop.style.width = "min(860px,96vw)";
  pop.style.maxHeight = "88vh";
  pop.style.overflow = "auto";
  try {
    const at = anchor.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(window.innerWidth - 880,
                                          at.left - 420)) + "px";
    pop.style.top = (at.bottom + 8) + "px";
  } catch (e) {
    pop.style.left = "40px";
    pop.style.top = "70px";
  }
  pop.onclick = (e) => e.stopPropagation();

  const head = mk("div", "wk-head");
  head.appendChild(mk("b", "", "🧹 the cache"));
  const sub = mk("span", "wk-sub", "every listing — play it, keep it, "
    + "read it, or let it go");
  head.appendChild(sub);
  const x = mk("button", "wk-x", "✕");
  x.onclick = () => pop.remove();
  head.appendChild(x);
  pop.appendChild(head);

  const body = mk("div", "");
  body.style.marginTop = "5px";
  pop.appendChild(body);

  const foot = mk("div", "");
  foot.style.cssText = "display:flex;align-items:center;gap:8px;"
    + "margin-top:9px;padding-top:8px;border-top:1px solid #24384a;"
    + "position:sticky;bottom:0;background:var(--panel,#0f1620)";
  const go = mk("button", "", "purge what is ticked");
  go.style.cssText = "padding:4px 11px;border-radius:7px;font-size:11px;"
    + "border:1px solid #6b4a1f;background:#221709;color:#ffb35e;"
    + "cursor:pointer";
  const note = mk("span", "wk-sub", "nothing ticked");
  note.style.fontSize = "9.5px";
  foot.appendChild(go);
  foot.appendChild(note);
  pop.appendChild(foot);
  document.body.appendChild(pop);
  try { wkDraggable(pop); } catch (e) { /* it still opens */ }

  /* What is ticked, in three registers that purge three different ways:
     whole live shelves, individual takes by key, and disk areas. */
  const tick = { live: {}, keys: {}, disk: {} };
  const count = () => Object.keys(tick.live).length
    + Object.keys(tick.keys).length + Object.keys(tick.disk).length;
  const retally = () => {
    const n = count();
    note.textContent = n ? n + " ticked" : "nothing ticked";
  };

  const cap = (text, hint) => {
    const h = mk("div", "wk-note", text);
    h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:8px 0 2px;"
      + "opacity:.8";
    body.appendChild(h);
    if (hint) {
      const b = mk("div", "wk-sub", hint);
      b.style.cssText = "font-size:9px;line-height:1.5;margin-bottom:3px";
      body.appendChild(b);
    }
  };

  const check = (bag, key) => {
    const cb = mk("input", "wk-check");
    cb.type = "checkbox";
    cb.onchange = () => {
      if (cb.checked) bag[key] = 1; else delete bag[key];
      retally();
    };
    return cb;
  };

  /* One table. `cols` is the grid template; `heads` label them. */
  const table = (host, cols, heads) => {
    const wrap = mk("div", "wk-scroll");
    const grid = mk("div", "wk-tbl");
    grid.style.gridTemplateColumns = cols;
    heads.forEach((h) => {
      const c = mk("div", "hd", h);
      grid.appendChild(c);
    });
    wrap.appendChild(grid);
    host.appendChild(wrap);
    return grid;
  };

  const play = (row) => {
    const b = mk("button", "wk-ico", "▶");
    b.title = "Play this take";
    let audio = null;
    b.onclick = (ev) => {
      ev.stopPropagation();
      if (audio) {
        try { audio.pause(); } catch (e) {}
        audio = null; b.textContent = "▶"; return;
      }
      if (!(row.media && row.sig)) { b.textContent = "✗"; return; }
      try {
        audio = new Audio(desktopMusicUrl("/media/"
          + encodeURIComponent(row.media) + "?t="
          + encodeURIComponent(row.sig)));
        audio.onended = () => { audio = null; b.textContent = "▶"; };
        audio.onerror = () => { audio = null; b.textContent = "✗"; };
        audio.play();
        b.textContent = "⏹";
      } catch (e) { audio = null; }
    };
    return b;
  };

  const keep = (row) => {
    const b = mk("button", "wk-ico", "⬇");
    b.title = "Download this take";
    b.onclick = (ev) => {
      ev.stopPropagation();
      if (!(row.media && row.sig)) return;
      const url = desktopMusicUrl("/media/" + encodeURIComponent(row.media)
        + "?t=" + encodeURIComponent(row.sig));
      wkSaveBlob(url, wkFileName((row.name || row.who || "take") + " "
        + (row.text || ""), String(row.media).split(".").pop() || "wav"), b);
    };
    return b;
  };

  const read = (row) => {
    const b = mk("button", "wk-ico", "📄");
    b.title = "Read the whole line";
    b.onclick = (ev) => { ev.stopPropagation(); wkTakeText(row); };
    return b;
  };

  const load = async () => {
    body.textContent = "";
    let live = null;
    let disk = null;
    let pantry = null;
    try { live = await api.get("/api/cache/state"); } catch (e) { live = null; }
    try { pantry = await api.get("/api/pantry/table?most=400"); }
    catch (e) { pantry = null; }
    try { disk = await api.get("/api/storage"); } catch (e) { disk = null; }

    if (live) {
      sub.textContent = wkMB(live.bytes) + " of " + wkMB(live.cap_bytes)
        + " · every listing, play / keep / read / let go";
    }

    /* --- the live shelves, one row each --------------------------- */
    if (live && live.areas) {
      cap("THE LIVE SHELVES",
          "In memory. Emptying one is what makes the coordinator start "
          + "queueing the hour's work again.");
      const g = table(body, "16px 1fr 70px 70px 80px",
                      ["", "shelf", "rows", "airtime", "size"]);
      live.areas.forEach((a) => {
        g.appendChild(check(tick.live, a.key));
        const nm = mk("div", "cel", a.key + " — " + a.label);
        nm.title = a.label;
        g.appendChild(nm);
        g.appendChild(mk("div", "cel", String(a.rows || 0)));
        g.appendChild(mk("div", "cel",
          a.seconds ? Math.round(a.seconds) + "s" : "—"));
        g.appendChild(mk("div", "cel", a.bytes ? wkMB(a.bytes) : "—"));
      });
    }

    /* --- EVERY TAKE, the thing that was actually asked for --------- */
    if (pantry && (pantry.rows || []).length) {
      cap("EVERY TAKE ON THE SHELF",
          pantry.shown + " of " + pantry.takes + " · "
          + Math.round((pantry.seconds || 0) / 60) + " min · "
          + pantry.loose + " loose (nothing is holding them — those "
          + "roll off first)");
      const bar = mk("div", "");
      bar.style.cssText = "display:flex;gap:6px;align-items:center;"
        + "margin-bottom:3px";
      const find = mk("input", "");
      find.type = "text";
      find.placeholder = "filter by what it says, who says it, or kind…";
      find.style.cssText = "flex:1 1 auto;min-width:0;font-size:9.5px;"
        + "padding:3px 7px;border-radius:6px";
      bar.appendChild(find);
      const looseOnly = mk("label", "");
      looseOnly.style.cssText = "display:flex;align-items:center;gap:4px;"
        + "font-size:9.5px;flex:0 0 auto;cursor:pointer";
      const lcb = mk("input", "wk-check");
      lcb.type = "checkbox";
      looseOnly.appendChild(lcb);
      looseOnly.appendChild(mk("span", "", "loose only"));
      bar.appendChild(looseOnly);
      const all = mk("button", "wk-pill", "tick shown");
      all.title = "Tick every take currently listed";
      bar.appendChild(all);
      body.appendChild(bar);

      const g = table(body,
        "16px 58px 1fr 44px 60px 52px 74px 78px",
        ["", "who", "what it says", "len", "size", "age", "held by",
         "play keep read"]);
      const draw = () => {
        while (g.children.length > 8) g.removeChild(g.lastChild);
        const q = String(find.value || "").toLowerCase().trim();
        let shown = 0;
        (pantry.rows || []).forEach((r) => {
          if (lcb.checked && !r.loose) return;
          if (q) {
            const hay = ((r.text || "") + " " + (r.name || "") + " "
              + (r.who || "") + " " + (r.label || "")).toLowerCase();
            if (hay.indexOf(q) < 0) return;
          }
          shown += 1;
          g.appendChild(check(tick.keys, r.key));
          const who = mk("div", "cel", r.name || r.who || "—");
          who.style.color = "#7ce8a9";
          g.appendChild(who);
          const said = mk("div", "cel", r.text || "(no words kept)");
          said.title = r.text || "";
          said.style.color = r.text ? "#c8d6e4" : "#6d8199";
          g.appendChild(said);
          g.appendChild(mk("div", "cel",
            r.seconds ? Math.round(r.seconds) + "s" : "—"));
          g.appendChild(mk("div", "cel", wkMB(r.bytes)));
          g.appendChild(mk("div", "cel",
            r.age_minutes >= 60
              ? (r.age_minutes / 60).toFixed(1) + "h"
              : Math.round(r.age_minutes) + "m"));
          const held = mk("div", "cel", r.held_by || "loose");
          held.style.color = r.held_by ? "#8ba0b5" : "#f0a35e";
          held.title = r.held_by
            ? "held by " + r.held_by
            : "nothing is holding this one — the horizon rolls it "
              + "off first";
          g.appendChild(held);
          const acts = mk("div", "");
          acts.style.cssText = "display:flex;gap:3px";
          acts.appendChild(play(r));
          acts.appendChild(keep(r));
          acts.appendChild(read(r));
          g.appendChild(acts);
        });
        if (!shown) {
          const none = mk("div", "cel", "nothing matches that");
          none.style.cssText = "grid-column:1/-1;opacity:.6;padding:4px 0";
          g.appendChild(none);
        }
      };
      let t = 0;
      find.oninput = () => { clearTimeout(t); t = setTimeout(draw, 140); };
      lcb.onchange = draw;
      all.onclick = () => {
        const q = String(find.value || "").toLowerCase().trim();
        (pantry.rows || []).forEach((r) => {
          if (lcb.checked && !r.loose) return;
          if (q) {
            const hay = ((r.text || "") + " " + (r.name || "") + " "
              + (r.who || "") + " " + (r.label || "")).toLowerCase();
            if (hay.indexOf(q) < 0) return;
          }
          tick.keys[r.key] = 1;
        });
        draw();
        // re-check the boxes the redraw just made
        Array.prototype.forEach.call(
          g.querySelectorAll("input.wk-check"), (cb) => { cb.checked = true; });
        retally();
      };
      draw();
    }

    /* --- the store room, on disk ---------------------------------- */
    const areas = ((disk && disk.areas) || []).filter((a) => a.purgeable
      && Number(a.bytes || 0) > 0);
    if (areas.length) {
      cap("THE STORE ROOM — on disk",
          "Ticking one empties that folder. Anything still playing out, "
          + "and anything written in the last few minutes, is kept.");
      areas.sort((a, b) => Number(b.bytes || 0) - Number(a.bytes || 0));
      const g = table(body, "16px 1fr 70px 80px", ["", "area", "files", "size"]);
      areas.slice(0, 30).forEach((a) => {
        g.appendChild(check(tick.disk, a.key));
        const nm = mk("div", "cel", String(a.label || a.key));
        nm.title = String(a.holds || "");
        g.appendChild(nm);
        g.appendChild(mk("div", "cel", String(a.files || 0)));
        g.appendChild(mk("div", "cel", wkMB(a.bytes)));
      });
    }

    if (!body.firstChild) {
      body.appendChild(mk("div", "wk-note",
                          "nothing is cached and nothing is stored"));
    }
    retally();
  };
  load();

  go.onclick = async () => {
    const liveKeys = Object.keys(tick.live);
    const takeKeys = Object.keys(tick.keys);
    const diskKeys = Object.keys(tick.disk);
    if (!liveKeys.length && !takeKeys.length && !diskKeys.length) {
      note.textContent = "nothing is ticked";
      return;
    }
    const what = [];
    if (liveKeys.length) what.push(liveKeys.join(", "));
    if (takeKeys.length) what.push(takeKeys.length + " take(s)");
    if (diskKeys.length) what.push(diskKeys.join(", "));
    if (!window.confirm("Purge " + what.join(" + ")
                        + "? The station makes this material again.")) return;
    go.disabled = true;
    note.textContent = "purging…";
    let freed = 0;
    const said = [];
    try {
      if (liveKeys.length) {
        const r = await api.post("/api/cache/purge", {areas: liveKeys});
        freed += Number((r && r.freed) || 0);
        Object.keys((r && r.dropped) || {}).forEach((k) =>
          said.push(k + " " + r.dropped[k]));
      }
      if (takeKeys.length) {
        const r = await api.post("/api/cache/purge", {keys: takeKeys});
        freed += Number((r && r.freed) || 0);
        said.push(((r && r.dropped && r.dropped.takes) || 0) + " take(s)");
      }
      for (let i = 0; i < diskKeys.length; i += 1) {
        const r = await api.post(
          "/api/storage/" + encodeURIComponent(diskKeys[i]) + "/purge",
          {keep_bytes: 0});
        freed += Number((r && r.freed) || 0);
        if (r && r.count) said.push(diskKeys[i] + " " + r.count + " file(s)");
      }
      note.textContent = "purged — " + wkMB(freed) + " freed"
        + (said.length ? " (" + said.join("; ") + ")" : "");
      tick.live = {}; tick.keys = {}; tick.disk = {};
      load();
    } catch (e) {
      note.textContent = "purge failed: " + ((e && e.message) || String(e));
    }
    go.disabled = false;
  };
}


/* #964 — THE LAST LINE THE ROOM MADE, on one line.
 *
 * Play it, keep it, or read it — the three things you want from a take
 * you have just watched being cut, without leaving the window. The take
 * ledger carries the signed media name since #964, so this needs no
 * second round trip. */
function wkLastLine(host, take, head) {
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  /* #959: the heading is optional now, so the same row can be used once
   * for "the last line made" and ten times for the list below it -
   * rather than growing a second take row that would drift out of step
   * with this one's play/save/transcript behaviour. */
  if (head !== "") {
    const h = mk("div", "wk-note", head || "THE LAST LINE MADE");
    h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:7px 0 2px;"
      + "opacity:.8";
    host.appendChild(h);
  }
  const row = mk("div", "");
  row.style.cssText = "display:flex;align-items:center;gap:6px;"
    + "font-size:10px;line-height:1.5;padding:5px 7px;border-radius:6px;"
    + "background:#05090f;border:1px solid #24384a";
  /* desktopMusicUrl is the renderer's one absolute-URL helper — the
   * page is loaded from file://, so a bare "/media/..." resolves at the
   * app itself and 404s. Every other player in here goes through it. */
  const url = (take.media && take.sig)
    ? desktopMusicUrl("/media/" + encodeURIComponent(take.media)
                      + "?t=" + encodeURIComponent(take.sig))
    : "";
  const btn = (label, title) => {
    const b = mk("button", "", label);
    b.title = title;
    b.style.cssText = "flex:0 0 auto;width:22px;height:22px;padding:0;"
      + "display:inline-flex;align-items:center;justify-content:center;"
      + "border:1px solid #24384a;border-radius:6px;background:#0b1520;"
      + "color:#9fd8ff;font-size:11px;line-height:1;cursor:pointer";
    return b;
  };
  if (url) {
    const play = btn("▶", "Play this take — click again to stop");
    let audio = null;
    play.onclick = (ev) => {
      ev.stopPropagation();
      if (audio) {
        try { audio.pause(); } catch (e) {}
        audio = null;
        play.textContent = "▶";
        return;
      }
      try {
        audio = new Audio(url);
        audio.onended = () => { audio = null; play.textContent = "▶"; };
        audio.onerror = () => { audio = null; play.textContent = "▶"; };
        audio.play();
        play.textContent = "⏹";
      } catch (e) { audio = null; }
    };
    row.appendChild(play);
    const save = btn("⬇", "Download this take");
    /* The save goes through the shell, the way every other download in
     * this window does — main.js owns the save dialog and remembers the
     * folder (#808); an <a download> from file:// does not. */
    save.onclick = (ev) => {
      ev.stopPropagation();
      try { api.openExternal(url); } catch (e) { /* nothing to save */ }
    };
    row.appendChild(save);
  }
  const doc = btn("📄", "Read the whole line");
  doc.onclick = (ev) => {
    ev.stopPropagation();
    wkTakeText(take);
  };
  row.appendChild(doc);
  const who = mk("b", "", String(take.name || take.who || "the booth"));
  who.style.cssText = "flex:0 0 auto;color:#7ce8a9";
  row.appendChild(who);
  const said = mk("span", "", String(take.text || ""));
  said.style.cssText = "flex:1 1 auto;min-width:0;color:#c8d6e4;"
    + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
  said.title = String(take.text || "");
  row.appendChild(said);
  const fig = mk("span", "",
    Math.round(Number(take.seconds) || 0) + "s"
    + (take.how === "shelf" ? " · off the shelf" : "")
    + (take.engine ? " · " + take.engine : ""));
  fig.style.cssText = "flex:0 0 auto;color:#6d8199;font-size:9px";
  row.appendChild(fig);
  host.appendChild(row);
}

/* The take's own words, in full, in a small window of their own. */
function wkTakeText(take) {
  const gone = document.getElementById("wkTakeText");
  if (gone) gone.remove();
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pop = mk("div", "works-pop");
  pop.id = "wkTakeText";
  pop.style.width = "min(460px,92vw)";
  pop.style.left = "50%";
  pop.style.top = "16vh";
  pop.style.transform = "translateX(-50%)";
  pop.onclick = (e) => e.stopPropagation();
  const head = mk("div", "wk-head");
  head.appendChild(mk("b", "", "📄 the take"));
  head.appendChild(mk("span", "wk-sub",
    String(take.name || take.who || "") + " · "
    + Math.round(Number(take.seconds) || 0) + "s"
    + (take.voice ? " · " + take.voice : "")));
  const x = mk("button", "wk-x", "✕");
  x.onclick = () => pop.remove();
  head.appendChild(x);
  pop.appendChild(head);
  const body = mk("div", "", String(take.text || "(no words recorded)"));
  body.style.cssText = "font-size:11px;line-height:1.6;white-space:pre-wrap;"
    + "margin-top:6px;padding:7px 9px;border-radius:7px;background:#05090f;"
    + "border:1px solid #24384a;color:#c8d6e4;max-height:60vh;overflow:auto";
  pop.appendChild(body);
  document.body.appendChild(pop);
  try { wkDraggable(pop); } catch (e) { /* it still opens */ }
}

/* ===================================================================
 * #958 — WHAT IS BEING DONE ABOUT IT.
 *
 * "I want to be able to click each of these entries and have a pop up
 *  that shows me what is being done about resolving them being behind.
 *  So anytime they're behind, if I click on that, I want to see a pop up
 *  explaining what is being done."
 *
 * The readouts said a road was behind and stopped there. Everything
 * needed to answer the next question already existed on the server —
 * the coordinator's ranked plan, the preparer's own candidate table with
 * its costs and its refusals, the coming entries with a clock on each,
 * the shelf, the quota ring, the lookahead log — scattered across five
 * endpoints and joined up nowhere. /api/coordinator/road/{road} joins
 * them, and this is the window it draws.
 * =================================================================== */
const WK_ROAD_TAG = {
  now: ["#7ce8a9", "● on it now"],
  next: ["#9fd8ff", "▸ queued"],
  blocked: ["#f0a35e", "⚠ held up"],
  due: ["#ffb35e", "⏱ the deadline"],
  clear: ["#8ba0b5", "✓ clear"],
};

function wkRoadPop(road, anchor) {
  const gone = document.getElementById("wkRoadPop");
  if (gone) {
    const was = gone.dataset.road;
    gone.remove();
    if (was === String(road)) return;          // clicking it again closes
  }
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pop = mk("div", "works-pop wk-road");
  pop.id = "wkRoadPop";
  pop.dataset.road = String(road);
  pop.style.width = "min(500px,92vw)";
  pop.style.maxHeight = "80vh";
  pop.style.overflow = "auto";
  try {
    const at = anchor.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(window.innerWidth - 520,
                                          at.left - 60)) + "px";
    pop.style.top = Math.min(window.innerHeight - 200,
                             at.bottom + 8) + "px";
  } catch (e) {
    pop.style.left = "40px";
    pop.style.top = "80px";
  }
  pop.onclick = (e) => e.stopPropagation();
  const head = mk("div", "wk-head");
  head.appendChild(mk("b", "", "⚙ " + String(road)));
  const sub = mk("span", "wk-sub", "what is being done about it");
  head.appendChild(sub);
  const x = mk("button", "wk-x", "✕");
  x.onclick = () => { clearInterval(tick); pop.remove(); };
  head.appendChild(x);
  pop.appendChild(head);
  const body = mk("div", "");
  pop.appendChild(body);
  document.body.appendChild(pop);
  try { wkDraggable(pop); } catch (e) { /* it still opens */ }

  const put = (label, text, colour) => {
    if (!text) return;
    const h = mk("div", "wk-note", label);
    h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:7px 0 2px;"
      + "opacity:.8";
    body.appendChild(h);
    const b = mk("div", "", String(text));
    b.style.cssText = "font-size:10.5px;line-height:1.55;white-space:pre-wrap;"
      + "padding:5px 7px;border-radius:6px;background:#05090f;"
      + "border:1px solid #24384a" + (colour ? ";color:" + colour : "");
    body.appendChild(b);
  };

  const draw = async () => {
    let d = null;
    try {
      d = await api.get("/api/coordinator/road/"
                        + encodeURIComponent(String(road)));
    } catch (e) {
      if (!body.firstChild) {
        body.appendChild(mk("div", "wk-note",
                            "the coordinator is unreachable"));
      }
      return;
    }
    const sig = JSON.stringify([d.doing, d.owes, d.entries, d.shelf,
                                d.quota, d.plan && d.plan.kind]);
    if (body.wkSig === sig && body.firstChild) return;
    body.wkSig = sig;
    body.textContent = "";
    sub.textContent = String(d.label || road);

    /* The answer, first and largest: one row per thing genuinely
     * happening, in the order a person would want it. */
    const doing = d.doing || [];
    if (!doing.length) {
      body.appendChild(mk("div", "wk-note",
                          "nothing to report — this road is quiet"));
    }
    doing.forEach((row) => {
      const spec = WK_ROAD_TAG[row.tag] || WK_ROAD_TAG.clear;
      const line = mk("div", "");
      line.style.cssText = "display:flex;gap:7px;align-items:flex-start;"
        + "font-size:10.5px;line-height:1.55;margin:4px 0;padding:6px 8px;"
        + "border-radius:7px;background:#070d14;border:1px solid #1d2f3f;"
        + "border-left:3px solid " + spec[0];
      const tag = mk("b", "", spec[1]);
      tag.style.cssText = "flex:0 0 auto;color:" + spec[0]
        + ";font-size:9.5px;white-space:nowrap;padding-top:1px";
      line.appendChild(tag);
      const said = mk("div", "", String(row.text || ""));
      said.style.cssText = "flex:1 1 auto;min-width:0;color:#c8d6e4";
      line.appendChild(said);
      body.appendChild(line);
    });

    const owes = d.owes || {};
    put("THE ARITHMETIC",
        "the hours owe it " + Math.round(owes.owed_seconds || 0) + "s\n"
        + "it is holding " + Math.round(owes.held_seconds || 0) + "s\n"
        + "short by " + Math.round(owes.short_seconds || 0) + "s\n"
        + "on the shelf: " + ((d.shelf || {}).rows || 0) + " row(s) of "
        + ((d.shelf || {}).cap || 0)
        + " (ceiling " + ((d.shelf || {}).ceiling || 0) + ")\n"
        + "one of these costs about " + Math.round(d.cost_seconds || 0)
        + "s of room to make");

    const ents = d.entries || [];
    if (ents.length) {
      put("THE ENTRIES IT HAS TO FILL", ents.map((e) =>
        (e.covered ? "✓ " : "✗ ")
        + String(e.label || e.kind)
        + " — in " + Math.round(e.starts_in || 0) + "s, owns "
        + Math.round(e.owns_seconds || 0) + "s, holding "
        + Math.round(e.held_seconds || 0) + "s"
        + (e.covered ? "" : " (" + Math.round(e.short_seconds || 0)
                            + "s short)")).join("\n"));
    }

    const plan = d.plan || {};
    if (plan.why) {
      put("THE PREPARER'S LAST DECISION",
          "it chose: " + (plan.kind || "nothing") + "\n" + plan.why
          + "\ntier " + plan.tier + " · budget "
          + Math.round(plan.budget || 0) + "s · window "
          + Math.round(plan.room || 0) + "s · reserve "
          + Math.round(plan.cover || 0) + "s");
    }
    const task = d.task || null;
    if (task && task.why) put("THE COORDINATOR'S OWN NOTE", String(task.why));
    const log = d.log || [];
    if (log.length) {
      put("WHAT THE LOG SAYS ABOUT IT",
          log.map((r) => "• " + String(r.text || "")).join("\n"));
    }
  };
  draw();
  const tick = setInterval(() => {
    if (!document.getElementById("wkRoadPop")) { clearInterval(tick); return; }
    draw();
  }, 4000);
  pop.wkTick = tick;
}

/* #959 — one road of THE BOARD, with a tick that opens it.
 *
 * The board was nine lines of pre-formatted text. Each road is a row
 * now: the triangle opens what the rooms are actually holding for it,
 * and the same coordinator report the scheduler rows open. */
function wkBoardRow(host, k) {
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const key = "board:" + String(k.kind);
  const wrap = mk("div", "");
  wrap.style.cssText = "margin:1px 0";
  const head = mk("div", "");
  head.style.cssText = "display:flex;align-items:center;gap:5px;"
    + "font-size:10px;line-height:1.5;cursor:pointer";
  const tick = mk("span", "", wkOpenBoard[key] ? "▾" : "▸");
  tick.style.cssText = "flex:0 0 auto;color:#3f7fa8;font-size:9px;width:9px";
  head.appendChild(tick);
  const nm = mk("b", "", String(k.label || k.kind));
  nm.style.cssText = "flex:1 1 auto;min-width:0;color:"
    + (k.behind ? "#f0a35e" : "#9fd8ff");
  head.appendChild(nm);
  const fig = mk("span", "",
    (k.written || 0) + "w · " + (k.rendered || 0) + "/"
    + (k.lines || 0) + "L · " + (k.ready || 0) + " ready"
    + (k.seconds ? " · " + Math.round(k.seconds) + "s" : ""));
  fig.style.cssText = "flex:0 0 auto;color:"
    + ((k.ready || 0) > 0 ? "#7ce8a9" : "#8ba0b5") + ";font-size:9.5px";
  head.appendChild(fig);
  wrap.appendChild(head);
  const drawer = mk("div", "");
  drawer.style.cssText = "display:" + (wkOpenBoard[key] ? "block" : "none")
    + ";margin:3px 0 6px 14px;padding:5px 7px;border-radius:6px;"
    + "background:#070d14;border:1px solid #1d2f3f;font-size:10px;"
    + "line-height:1.55;color:#c8d6e4;white-space:pre-wrap";
  const fill = () => {
    drawer.textContent =
      "written — " + (k.written || 0) + " segment(s) off the model"
      + (k.cap ? " of " + k.cap + " the shelf holds" : "") + "\n"
      + "recorded — " + (k.rendered || 0) + " of " + (k.lines || 0)
      + " line(s) cut into the pantry\n"
      + "ready — " + (k.ready || 0)
      + " whole segment(s) that can air without touching the engine\n"
      + (k.recording ? "in the room now — " + k.recording + "\n" : "")
      + "airtime standing by — " + Math.round(k.seconds || 0) + "s"
      + (k.per_hour != null
         ? "\nthe hour — " + (k.aired || 0) + " aired of " + k.per_hour
           + (k.behind ? " (behind)" : " (on pace)") : "")
      + (k.short ? "\nshort of the hour's calls by " + k.short : "");
    const more = document.createElement("button");
    more.textContent = "what is being done about it →";
    more.style.cssText = "display:block;margin-top:6px;font-size:9.5px;"
      + "padding:3px 8px;border-radius:6px;border:1px solid #24384a;"
      + "background:#0b1520;color:#9fd8ff;cursor:pointer";
    more.onclick = (ev) => { ev.stopPropagation(); wkRoadPop(k.kind, more); };
    drawer.appendChild(more);
  };
  if (wkOpenBoard[key]) fill();
  head.onclick = (ev) => {
    ev.stopPropagation();
    wkOpenBoard[key] = !wkOpenBoard[key];
    try { localStorage.setItem("wkOpenBoard", JSON.stringify(wkOpenBoard)); }
    catch (e) { /* private mode */ }
    tick.textContent = wkOpenBoard[key] ? "▾" : "▸";
    drawer.style.display = wkOpenBoard[key] ? "block" : "none";
    if (wkOpenBoard[key]) fill();
  };
  wrap.appendChild(drawer);
  host.appendChild(wrap);
}
let wkOpenBoard = {};
try { wkOpenBoard = JSON.parse(localStorage.getItem("wkOpenBoard") || "{}"); }
catch (e) { wkOpenBoard = {}; }

/* #923 — THE HOUR, beside The Works.
 *
 * The Works answers "where is each round right now". This answers the
 * other half: what the HOUR is supposed to be, entry by entry, and what
 * the rooms have actually got ready for each one. It scrolls forward
 * into hours that have not happened yet, and anything changed there is
 * an override on that hour alone — the running order everywhere else is
 * untouched.
 */
/* #926: entries that can never be stacked ahead — say so on the bar
 * rather than drawing an empty one and letting it read as a failure. */
const CANNOT_SAY = {
  record: "a record is not written ahead — the needle just drops",
  recap: "written at the end of the hour it recaps",
  deep: "written from the last stretch of the show",
};
const SCHED_ICON = {news: "📰", record: "💿", gallery: "🖼", ad: "📣",
                    banter: "💬", banter_caller: "☎💬", caller: "☎",
                    manager: "📻", recap: "🔁", deep: "🧠",
                    bombshell: "🌶"};

function worksSchedule(anchorPop) {
  const gone = document.getElementById("worksSched");
  if (gone) gone.remove();
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pop = mk("div", "works-pop works-sched");
  pop.id = "worksSched";
  const at = anchorPop.getBoundingClientRect();
  pop.style.width = "min(430px,42vw)";
  pop.style.left = Math.round(at.right + 10) + "px";
  pop.style.top = Math.round(at.top) + "px";
  pop.style.maxHeight = "86vh";
  pop.onclick = (e) => e.stopPropagation();

  const head = mk("div", "wk-head");
  head.appendChild(mk("b", "", "🗓 the hour"));
  const sub = mk("span", "wk-sub", "");
  head.appendChild(sub);
  const x = mk("button", "wk-x", "✕");
  x.onclick = () => { clearInterval(tick); pop.remove(); };
  head.appendChild(x);
  /* #917: so The Works can stop this window's clock when it closes the
   * pair, rather than leaving an interval running against a removed
   * element. #914: and this half drags by its blank space too. */
  try {
    pop.wkTick = tick;
    wkDraggable(pop);
  } catch (e) { /* the sheet still opens */ }
  pop.appendChild(head);

  const nav = mk("div", "wk-note", "");
  nav.style.cssText = "display:flex;gap:6px;align-items:center;margin:2px 0 6px";
  const prev = mk("button", "", "‹");
  const label = mk("b", "", "");
  label.style.cssText = "flex:1;text-align:center;font-size:11.5px";
  const next = mk("button", "", "›");
  [prev, next].forEach((b) => {
    b.style.cssText = "font-size:11px;line-height:1;padding:1px 8px";
  });
  nav.appendChild(prev); nav.appendChild(label); nav.appendChild(next);
  pop.appendChild(nav);

  const body = mk("div", "");
  pop.appendChild(body);
  document.body.appendChild(pop);

  let offset = 0;              // hours forward from now
  let hour = null;             // the hour being shown
  let dragFrom = null;
  const segOpen = {};          // #927: which entries are open
  const segBody = {};          // ...and their drawers, kept across paints
  const segAt = {};            // when each was last filled

  /* #927: fill one entry with what is stacked for it. Throttled, and it
   * only rebuilds when the shelf actually changed — a drawer being read
   * must hold still. */
  async function segLoad(slot, drw, okey, force) {
    if (!force && Date.now() - (segAt[okey] || 0) < 4000) return;
    segAt[okey] = Date.now();
    let d = null;
    try {
      d = await api.get("/api/schedule/segment?kind="
        + encodeURIComponent(slot.kind) + "&hour="
        + encodeURIComponent(hour.key) + "&slot="
        + encodeURIComponent(slot.id));
    } catch (e) {
      if (!drw.childNodes.length) drw.textContent = "could not read that";
      return;
    }
    const sig = JSON.stringify((d.candidates || []).map(
      (c) => [c.id, c.priority, c.pinned, c.seconds, c.usable]))
      + "|" + String(d.pinned_id) + "|" + ((d.generating || []).length);
    if (drw.dataset.sig === sig) return;      // nothing moved; leave it be
    drw.dataset.sig = sig;
    drw.textContent = "";

    if (!d.preparable) {
      const w = mk("div", "wk-note", d.why || "this one is written live");
      w.style.cssText = "font-size:9.5px;opacity:.6";
      drw.appendChild(w);
      return;
    }
    const c2 = d.counts || {};
    const head = mk("div", "wk-note", "");
    head.style.cssText = "font-size:9.5px;opacity:.7;margin-bottom:3px";
    head.textContent = (c2.candidates || 0) + " stacked \u00b7 "
      + (c2.usable || 0) + " usable \u00b7 "
      + Math.round(c2.seconds || 0) + "s recorded \u00b7 shelf holds "
      + (d.cap || 0);
    drw.appendChild(head);

    (d.candidates || []).forEach((c, ix) => {
      const it = mk("div", "");
      it.style.cssText = "border:1px solid "
        + (c.pinned ? "rgba(120,220,140,.5)" : "#24384a")
        + ";border-radius:6px;padding:4px 6px;margin-bottom:4px;"
        + "background:rgba(255,255,255,.02);opacity:"
        + (c.usable === false ? ".45" : "1");
      const t1 = mk("div", "");
      t1.style.cssText = "display:flex;gap:5px;align-items:center;"
        + "font-size:10px";
      const mark = mk("b", "", c.pinned ? "\ud83d\udccc"
                       : ix === 0 ? "\u25b6" : String(ix + 1));
      mark.style.color = c.pinned ? "#7ce8a9"
                        : ix === 0 ? "#9fd8ff" : "#6d8199";
      mark.title = c.pinned ? "pinned - this one goes out"
                   : ix === 0 ? "next off the shelf" : "";
      t1.appendChild(mark);
      const ttl = mk("span", "", String(c.title || c.label || c.id));
      ttl.style.cssText = "flex:1;min-width:0;overflow:hidden;"
        + "text-overflow:ellipsis;white-space:nowrap;color:#9fd8ff;"
        + "cursor:pointer";
      /* #902: "If I click any of these show a pop up showing me the
       * transcript, the recording..." */
      ttl.title = "Open this one: the recording, every line of the "
        + "transcript, and your own version back through the rooms";
      ttl.onclick = (ev) => {
        ev.stopPropagation();
        try { wkReviewPopup(c.kind || slot.kind, c.id); }
        catch (e) { /* the list still works */ }
      };
      t1.appendChild(ttl);
      const meta = mk("span", "wk-note", "");
      meta.style.cssText = "font-size:9px;opacity:.7";
      meta.textContent = (c.lines || 0) + "L \u00b7 "
        + Math.round(c.seconds || 0) + "s"
        + (c.burns_in ? " \u00b7 burns in "
                        + Math.round(c.burns_in / 60) + "m" : "");
      t1.appendChild(meta);
      it.appendChild(t1);
      const pv = mk("div", "wk-note", String(c.preview || "").slice(0, 150));
      pv.style.cssText = "font-size:9px;line-height:1.45;opacity:.65;"
        + "margin-top:2px";
      it.appendChild(pv);
      if (c.usable === false && c.why) {
        const bad = mk("div", "wk-note", "\u26a0 " + c.why);
        bad.style.cssText = "font-size:9px;color:#e88c8c;margin-top:2px";
        it.appendChild(bad);
      }
      const acts = mk("div", "wk-actbar");                 // #966
      acts.style.marginTop = "3px";
      const bt = (txt, title, fn) => {
        const b = mk("button", wkBtnClass(txt), txt);      // #966
        b.title = title;
        b.onclick = async (ev) => {
          ev.stopPropagation();
          b.disabled = true;
          try { await fn(); } catch (e) {}
          segLoad(slot, drw, okey, true);
        };
        acts.appendChild(b);
      };
      bt(c.pinned ? "unpin" : "\ud83d\udccc use this one",
         "Pin this candidate to this entry, this hour",
         () => api.post("/api/schedule/segment/pin",
                        {hour: hour.key, slot: slot.id,
                         shelf_id: c.pinned ? null : c.id}));
      bt("\u25b2", "Push it up the order",
         () => api.post("/api/schedule/segment/priority",
                        {shelf_id: c.id, priority: (c.priority || 0) + 1}));
      bt("\u25bc", "Push it down the order",
         () => api.post("/api/schedule/segment/priority",
                        {shelf_id: c.id, priority: (c.priority || 0) - 1}));
      bt("\u2715", "Throw this candidate away (the audio is left alone)",
         () => api.del("/api/schedule/segment/" + encodeURIComponent(c.id)));
      it.appendChild(acts);
      /* #939: and the same three tape controls the pantry drawers have. */
      try { wkTapeBar(it, c.kind || slot.kind, c.id); } catch (e) { /* still listed */ }
      drw.appendChild(it);
    });

    if (!(d.candidates || []).length) {
      const none = mk("div", "wk-note", "nothing stacked for this entry yet");
      none.style.cssText = "font-size:9.5px;opacity:.6;margin-bottom:3px";
      drw.appendChild(none);
    }
    const gen = mk("button", "", "\u270e write another for this entry");
    gen.title = "Opens the system prompt this one will be WRITTEN with - "
      + "edit it, send it up, and what comes back stands in for this "
      + "entry this hour (#897)";
    gen.style.cssText = "font-size:9.5px;padding:2px 7px";
    /* #897: it no longer fires blind. The prompt that will write the
     * candidate goes in front of the operator first, and what comes back
     * is pinned as this entry's stand-in for the hour. */
    gen.onclick = (ev) => {
      ev.stopPropagation();
      promptDesk(slot, null,
                 {generate: true,
                  after: () => segLoad(slot, drw, okey, true)});
    };
    drw.appendChild(gen);
    (d.generating || []).forEach((g) => {
      const w = mk("div", "wk-note",
                   "\u270e writing\u2026 " + (g.state || ""));
      w.style.cssText = "font-size:9px;opacity:.7;margin-top:3px";
      drw.appendChild(w);
    });
  }

  const save = async (slots) => {
    if (!hour) return;
    try {
      const got = await api.post("/api/schedule/hours",
                                 {key: hour.key, slots: slots});
      hour = ((got && got.hours) || [])[0] || hour;
      paint();
    } catch (e) { sub.textContent = "could not save that"; }
  };

  const revert = async () => {
    if (!hour) return;
    try {
      await api.del("/api/schedule/hours/" + encodeURIComponent(hour.key));
    } catch (e) {}
    load();
  };

  function paint() {
    /* #883/#887: the hour sheet reloads every five seconds. It was
     * rebuilt every time, which threw the popup's scroll to the top
     * and tore the row you were reading out from under you. It is
     * only rebuilt when the hour has actually changed, and the
     * scroll goes back where it was either way. */
    const sig = JSON.stringify(hour || null);
    if (body.wkSig === sig && body.firstChild) { paintAir(); return; }
    body.wkSig = sig;
    const wasAt = pop.scrollTop;
    body.wkAir = null;
    body.textContent = "";
    if (!hour) { body.appendChild(mk("div", "wk-note", "reading…")); return; }
    label.textContent = hour.label + " · " + hour.date
      + (hour.is_now ? "  (on air)" : hour.is_past ? "  (aired)" : "");
    sub.textContent = hour.preset + (hour.overridden ? " · edited" : "")
      + (hour.is_past ? " · aired, inert" : "");
    if (hour.overridden) {
      const rv = mk("button", "", "↺ back to the running order");
      rv.style.cssText = "font-size:10px;margin-bottom:6px;padding:2px 7px";
      rv.onclick = revert;
      body.appendChild(rv);
    }
    /* #920: "I'm still able to modify them and schedule them for future
     * tasks." A past hour is a running order that has already proved
     * itself on air - this copies the whole of it onto a future hour,
     * where it is an ordinary hour override and every tile is live
     * again. Nothing about the past hour changes; it is a copy. */
    if (hour.is_past) {
      const fwd = mk("div", "wk-note", "");
      fwd.style.cssText = "display:flex;gap:5px;align-items:center;"
        + "flex-wrap:wrap;margin-bottom:6px;font-size:9.5px;opacity:.85";
      fwd.appendChild(mk("span", "", "this hour has aired · send it"));
      const num = mk("input", "");
      num.type = "number";
      num.value = "24";
      num.min = "1";
      num.max = "168";
      num.style.cssText = "width:54px;font-size:10px";
      fwd.appendChild(num);
      fwd.appendChild(mk("span", "", "hours on"));
      const go = mk("button", "", "\u21aa schedule it forward");
      go.title = "Copy this whole running order onto a future hour, "
        + "where it can actually be aired. The past hour is left alone.";
      go.style.cssText = "font-size:9.5px;padding:1px 6px";
      go.onclick = async (ev) => {
        ev.stopPropagation();
        const was = go.textContent;
        go.disabled = true;
        go.textContent = "\u2026";
        try {
          const key = hourKeyFrom(hour.key, Number(num.value) || 24);
          await api.post("/api/schedule/hours",
                         {key: key, slots: hour.slots || []});
          go.textContent = "\u2713 " + key;
        } catch (e) {
          go.textContent = "could not";
        }
        setTimeout(() => { go.textContent = was; go.disabled = false; },
                   4500);
      };
      fwd.appendChild(go);
      body.appendChild(fwd);
    }
    (hour.slots || []).forEach((s, i) => {
      const row = mk("div", "wk-stage");
      /* #920: a half hour the clock has gone past is INERT. Greyed right
       * down and desaturated so the sheet reads at a glance as "this has
       * already happened" - and yet every control on it still works,
       * because the operator asked to be able to modify a past tile and
       * schedule it forward. The one thing it cannot do is go on air
       * again, and that is the clock's decision rather than the panel's:
       * `past` is stamped on the tile by schedule_hours_view.
       *
       * The entry ON AIR is never greyed even when the sheet's own clock
       * has run past its minutes - the running order's walk is what says
       * which entry owns the air, and greying out the thing the station
       * is doing right now would be the sheet arguing with the booth. */
      const gone = !!s.past && s.state !== "on air";
      // #890: room for the corner icon, and nothing runs under it.
      row.style.cssText = "position:relative;padding:5px 34px 5px 8px;"
        + "margin:0 0 4px;border-left:3px solid "
        + (s.state === "on air" ? "#7ce8a9"
           : gone ? "#3a4553"
           : s.enabled === false ? "#44515f" : "#3f7fa8")
        + ";opacity:" + (gone ? ".45" : s.enabled === false ? ".5" : "1")
        + (gone ? ";filter:grayscale(.75)" : "");
      row.draggable = true;
      row.addEventListener("dragstart", () => { dragFrom = i; });
      row.addEventListener("dragover", (ev) => ev.preventDefault());
      row.addEventListener("drop", (ev) => {
        ev.preventDefault();
        if (dragFrom == null || dragFrom === i) return;
        const list = hour.slots.slice();
        const [moved] = list.splice(dragFrom, 1);
        list.splice(i, 0, moved);
        dragFrom = null;
        hour.slots = list;
        save(list);
      });
      const top = mk("div", "");
      top.style.cssText = "display:flex;gap:6px;align-items:center;"
        + "font-size:11px;cursor:grab";
      const t = mk("span", "wk-note", s.starts_at);
      t.style.cssText = "font-size:10px;opacity:.7;width:38px";
      top.appendChild(t);
      top.appendChild(mk("span", "", SCHED_ICON[s.kind] || "•"));
      const nm = mk("b", "", s.label || s.kind);
      nm.style.cssText = "flex:1;min-width:0;overflow:hidden;"
        + "text-overflow:ellipsis;white-space:nowrap";
      top.appendChild(nm);
      const mins = mk("span", "wk-note", s.minutes + "m");
      mins.style.cssText = "font-size:10px;opacity:.7";
      top.appendChild(mins);
      const onoff = mk("button", "wk-icon", s.enabled === false ? "○" : "●");
      onoff.title = s.enabled === false ? "Off — click to run it"
                                        : "On — click to skip it this hour";
      onoff.onclick = (ev) => {
        ev.stopPropagation();
        const list = hour.slots.map((r, j) =>
          j === i ? Object.assign({}, r, {enabled: !(r.enabled !== false)}) : r);
        hour.slots = list;
        save(list);
      };
      row.appendChild(onoff);            // #890: cornered, not in the flow
      row.appendChild(top);

      /* #940: the entry that owns the air is lit, not merely mentioned.
       * A dot inside a grey sentence is not "I can see which segment is
       * going on" — this is a bordered, tinted tile with its own
       * running clock. */
      if (s.state === "on air") {
        row.style.borderColor = "#7ce8a9";
        row.style.background = "rgba(124,232,169,.08)";
        row.style.boxShadow = "0 0 0 1px rgba(124,232,169,.35),"
          + "0 0 14px rgba(124,232,169,.16)";
        const flag = mk("div", "");
        flag.style.cssText = "font-size:9px;letter-spacing:.08em;"
          + "color:#7ce8a9;font-weight:700;margin-top:1px";
        flag.textContent = "● ON AIR NOW";
        row.appendChild(flag);
      }
      const p = s.prep || {};
      const line2 = mk("div", "wk-note", "");
      line2.style.cssText = "font-size:9.5px;margin-top:2px;opacity:.75";
      line2.textContent = (s.state === "on air" ? "● on air · " : "")
        + "the rooms hold " + (p.written || 0) + " written, "
        + (p.rendered || 0) + " recorded, " + (p.ready || 0) + " ready"
        + (p.seconds ? " · " + Math.round(p.seconds) + "s" : "");
      row.appendChild(line2);

      /* #926: the bar. How much finished audio stands behind this entry
       * against the minutes it owns — so an hour reads at a glance as a
       * row of columns filling up, and a hollow one is a segment with
       * nothing behind it. The entry ON AIR gets a second, brighter bar
       * showing how far through its own slot the clock is. */
      /* #965: "If a segment has all of the entries it needs to play, I
       * want to see that one."
       *
       * `p` is the per-KIND shelf, so three Painting-selling entries all
       * drew the same bar off the one gallery shelf and the second and
       * third read as stocked while nothing had been made for them.
       * `slot_prep` is the per-ENTRY figure, with the shelf spent down
       * across the entries ahead of it - the coordinator has computed it
       * correctly all along and it was simply never drawn here. */
      const sp = s.slot_prep || null;
      const need = Math.max(1, Number(s.minutes || 1) * 60);
      row.dataset.kind = String(s.kind || "");
      const have = sp ? Number(sp.held || 0) : Number(p.seconds || 0);
      const frac = Math.max(0, Math.min(1, have / need));
      /* #966: "When a segment is a hundred percent ready and able to be
       * played, I want an animation effect happening over that tile every
       * three to four seconds just showing that that tile is prepared and
       * slated." A sheen that crosses the tile, not a flash - twenty
       * tiles blinking at once would be unreadable. */
      const slated = !!(sp ? sp.covered : frac >= 0.999)
        && !gone && s.enabled !== false && !CANNOT_SAY[s.kind];
      if (slated) row.classList.add("slated");
      const bar = mk("div", "wk-bar");
      /* #940: an empty fill on a dark ground reads as NO BAR. The track
       * is drawn explicitly so an empty segment looks empty rather than
       * looking like a segment with no bar. */
      bar.style.cssText = "margin-top:4px;background:rgba(255,255,255,.13);"
        + "border:1px solid rgba(255,255,255,.10)";
      const fillb = mk("div", "wk-fill"
        + (frac >= 0.999 ? " good" : frac < 0.15 ? " warn" : ""));
      fillb.style.width = (frac > 0 ? Math.max(2, Math.round(frac * 100))
                                    : 0) + "%";
      bar.appendChild(fillb);
      row.appendChild(bar);
      const cap = mk("div", "wk-note", "");
      cap.style.cssText = "font-size:9px;opacity:.55;margin-top:1px";
      cap.textContent = CANNOT_SAY[s.kind]
        ? CANNOT_SAY[s.kind]
        : Math.round(have) + "s banked of " + Math.round(need)
          + "s this entry owns"
          // #965: say WHICH entry it is when the shelf is shared, so
          // "covered" on the first and "bare" on the third reads as the
          // truth about the running order rather than a contradiction.
          + (sp ? (sp.covered ? " · ready to play"
                   : sp.bare ? " · nothing behind it yet"
                   : " · short by " + Math.round(Math.max(0, need - have))
                     + "s") : "");
      row.appendChild(cap);
      if (s.state === "on air" && hour.now && hour.now.started) {
        const started = Number(hour.now.started);
        const through = Math.max(0, Math.min(1,
          (Date.now() / 1000 - started) / need));
        const b2 = mk("div", "wk-bar");
        b2.style.cssText = "margin-top:3px;height:4px;"
          + "background:rgba(124,232,169,.16)";
        const f2 = mk("div", "wk-fill good");
        f2.style.width = Math.round(through * 100) + "%";
        b2.appendChild(f2);
        row.appendChild(b2);
        /* #940: and the clock in words beside it, so the tile says how
         * far through its own slot it is without being measured by eye. */
        const clock = mk("div", "wk-note", "");
        clock.style.cssText = "font-size:9px;color:#7ce8a9;margin-top:1px";
        const say = () => {
          const el = Math.max(0, Date.now() / 1000 - started);
          clock.textContent = Math.round(Math.min(el, need)) + "s of "
            + Math.round(need) + "s through this entry \u00b7 "
            + Math.round(Math.min(1, el / need) * 100) + "%";
        };
        say();
        row.appendChild(clock);
        body.wkAir = f2;              // nudged in place between rebuilds
        body.wkAirNeed = need;
        body.wkAirClock = say;        // #940: and the words tick too
      }
      /* #910/#965: A DOWNLOAD IN THE CORNER OF EVERY ENTRY.
       *
       * "For each option in the hour, offer a download button that I can
       *  click to download that segment for the broadcast for the hour —
       *  to just download just that section in general."
       *
       * It used to be the on-air entry's alone, on the reasoning that
       * "the currently aired interaction" is something exactly one entry
       * has at a time. True, and beside the point: what the operator
       * wants off a coming entry is what is STACKED for it, and off a
       * past one what actually WENT OUT. Every entry has one of those,
       * so every entry has a button — and one that genuinely has nothing
       * says so on the button rather than not being there. */
      try { wkEntryGrab(row, hour, s, gone); }
      catch (e) { /* the tile still draws */ }

      /* #920: and the DOWNLOAD of what actually went out in this entry.
       * Only a tile the clock has finished with has one. The server
       * welds it out of the booth's own record of what aired inside this
       * entry's span, keeps it for two hours and then deletes it - after
       * which this says "deleted" rather than handing over the nearest
       * thing to it and letting the operator find out on playback. */
      if (gone) {
        const tape = mk("div", "wk-note", "");
        tape.style.cssText = "font-size:9px;margin-top:3px;display:flex;"
          + "gap:5px;align-items:center;flex-wrap:wrap";
        const inert = mk("span", "", "\u25cf inert · already aired");
        inert.style.cssText = "color:#8fa2b6;opacity:.9";
        tape.appendChild(inert);
        const keep = mk("button", "", "\u2b07 keep what aired");
        keep.title = "Download what actually went out in this entry, "
          + "welded into one file. Kept for two hours after it airs, "
          + "then deleted.";
        keep.style.cssText = "font-size:9px;padding:1px 6px";
        keep.onclick = async (ev) => {
          ev.stopPropagation();
          const was = keep.textContent;
          keep.disabled = true;
          keep.textContent = "\u2026";
          let got = null;
          try {
            got = await api.get("/api/schedule/aired?hour="
              + encodeURIComponent(hour.key) + "&slot="
              + encodeURIComponent(s.id));
          } catch (e) { got = null; }
          if (!got || !got.ready) {
            keep.textContent = got && got.pruned ? "deleted" : "nothing kept";
            keep.title = (got && got.why)
              || "the station could not be asked for this one";
            setTimeout(() => {
              keep.textContent = was;
              keep.disabled = false;
            }, 6000);
            return;
          }
          keep.textContent = was;
          keep.disabled = false;
          await wkSaveBlob(
            wkMediaUrl(got),
            wkFileName(hour.date + " " + (s.starts_at || "") + " "
                       + (s.label || s.kind),
                       String(got.media || "x.wav").split(".").pop()),
            keep);
        };
        tape.appendChild(keep);
        const held = mk("span", "wk-note", "");
        held.style.cssText = "font-size:9px;opacity:.55";
        held.textContent = "kept 2h";
        tape.appendChild(held);
        row.appendChild(tape);
      }

      const gear = mk("button", "", "⚙ this entry, this hour");
      gear.style.cssText = "font-size:9.5px;margin-top:3px;padding:1px 6px";
      gear.onclick = (ev) => { ev.stopPropagation(); detail(s, i); };
      row.appendChild(gear);

      /* #909: and the entry's SYSTEM PROMPT, one click away - which is
       * the thing the operator was actually clicking when he asked for a
       * pop-up he could edit, save and swap between. */
      const prm = mk("button", "", "\ud83d\udcdd prompt");
      prm.title = "Edit the system prompt this entry writes with, save it "
        + "by name, and choose how long it runs for";
      prm.style.cssText = "font-size:9.5px;margin:3px 0 0 6px;"
        + "padding:1px 6px";
      prm.onclick = (ev) => { ev.stopPropagation(); promptDesk(s, i, {}); };
      row.appendChild(prm);

      /* #927: and the entry OPENS onto what is stacked for it. */
      const okey = "seg:" + hour.key + ":" + s.id;
      const tri = mk("button", "",
                     (segOpen[okey] ? "\u25be" : "\u25b8")
                     + " what is stacked");
      tri.style.cssText = "font-size:9.5px;margin:3px 0 0 6px;padding:1px 6px";
      const drw = segBody[okey] || mk("div", "");
      segBody[okey] = drw;
      drw.style.display = segOpen[okey] ? "block" : "none";
      drw.style.marginTop = "4px";
      /* #903: "If I click the title of a section, expand that section.
       * and collapse it." The little triangle down at the bottom of the
       * tile was the only way in - the entry's own NAME, which is the
       * thing anybody actually aims at, did nothing at all. One toggle,
       * two handles. */
      const segToggle = (ev) => {
        if (ev) ev.stopPropagation();
        segOpen[okey] = !segOpen[okey];
        tri.textContent = (segOpen[okey] ? "\u25be" : "\u25b8")
                          + " what is stacked";
        drw.style.display = segOpen[okey] ? "block" : "none";
        if (segOpen[okey]) segLoad(s, drw, okey, true);
      };
      tri.onclick = segToggle;
      nm.style.cursor = "pointer";
      nm.title = "Click the name to open or close what is stacked for "
        + "this entry";
      nm.onclick = segToggle;
      row.appendChild(tri);
      row.appendChild(drw);
      if (segOpen[okey]) segLoad(s, drw, okey);

      /* #928 (#891): a Spin record entry gets a play icon — pick the
       * track that fills it. Pinning QUEUES the track; it never cuts a
       * record that is still turning. */
      if (s.kind === "record") {
        const pick = mk("button", "",
                        (s.track_id ? "\u25b6 " + String(s.track || "pinned")
                                    : "\u25b6 choose the record"));
        pick.title = s.track_id
          ? "This track fills the entry. Click to change or unpin it."
          : "Pick the track that fills this entry, this hour";
        pick.style.cssText = "font-size:9.5px;margin:3px 0 0 6px;"
          + "padding:1px 6px;max-width:230px;overflow:hidden;"
          + "text-overflow:ellipsis;white-space:nowrap"
          + (s.track_id ? ";color:#7ce8a9" : "");
        pick.onclick = (ev) => { ev.stopPropagation(); trackPick(s); };
        row.appendChild(pick);
      }
      body.appendChild(row);
    });
    try {
      pop.scrollTop = wasAt;
      requestAnimationFrame(() => {
        try { pop.scrollTop = wasAt; } catch (e) { /* fine */ }
      });
    } catch (e) { /* the sheet is drawn either way */ }
  }

  /* The one thing that moves between rebuilds: how far the clock is
   * through the entry on air. Nudged in place, nothing torn down. */
  function paintAir() {
    try {
      if (!body.wkAir || !body.wkAir.isConnected) return;
      if (!hour || !hour.now || !hour.now.started) return;
      const need = Math.max(1, Number(body.wkAirNeed || 1));
      const through = Math.max(0, Math.min(1,
        (Date.now() / 1000 - Number(hour.now.started)) / need));
      body.wkAir.style.width = Math.round(through * 100) + "%";
      /* #940: and the words beside it, so the tile's clock runs rather
       * than jumping whenever the sheet happens to reload. */
      if (typeof body.wkAirClock === "function") body.wkAirClock();
    } catch (e) { /* the bar is cosmetic */ }
  }

  /* #928: search the library and pin one track to this entry. */
  function trackPick(slot) {
    const old = document.getElementById("worksTrackPick");
    if (old) old.remove();
    const d = mk("div", "works-pop");
    d.id = "worksTrackPick";
    const r = pop.getBoundingClientRect();
    d.style.cssText = "position:fixed;z-index:403;width:min(420px,44vw);"
      + "max-height:70vh;overflow:auto;left:"
      + Math.max(8, Math.round(r.left - 30)) + "px;top:"
      + Math.round(r.top + 60) + "px";
    d.onclick = (e) => e.stopPropagation();
    const h = mk("div", "wk-head");
    h.appendChild(mk("b", "", "\u25b6 the record for this entry"));
    const cx = mk("button", "wk-x", "\u2715");
    cx.onclick = () => d.remove();
    h.appendChild(cx);
    d.appendChild(h);
    d.appendChild(mk("div", "wk-sub",
      hour.label + " on " + hour.date + " \u00b7 " + (slot.label || "")
      + " \u00b7 this hour only. Pinning QUEUES the track \u2014 it never "
      + "cuts a record that is still playing."));

    const box = mk("input", "");
    box.placeholder = "search your library\u2026";
    box.style.cssText = "width:100%;font-size:11px;margin:6px 0";
    d.appendChild(box);
    const list = mk("div", "");
    d.appendChild(list);

    const pin = async (id, title) => {
      try {
        await api.post("/api/schedule/hours/"
                       + encodeURIComponent(hour.key) + "/track",
                       {slot_id: slot.id, track_id: id || "",
                        track: title || ""});
      } catch (e) {}
      d.remove();
      load();
    };
    if (slot.track_id) {
      const un = mk("button", "", "unpin \u2014 let the queue decide");
      un.style.cssText = "font-size:10px;margin-bottom:6px;padding:2px 7px";
      un.onclick = () => pin("", "");
      d.appendChild(un);
    }
    /* #967 — THE SEARCH THAT NEVER MATCHED ANYTHING.
     *
     * "When I'm choosing a record and typing in the pop-up, I want it to
     *  be showing suggestions of people in my library and allow me to
     *  explore them by clicking on them and finding the right song and
     *  album in the library by going through the advanced search that's
     *  basically growing and auto populating as I'm typing in."
     *
     * The first fault was one word. /api/music/search answers
     * {query, results} and /api/music/browse answers {total, results};
     * this read `got.tracks || got.rows || got.items` and then fell back
     * to "is it an array" — so EVERY search, however good, drew the
     * empty list and said "nothing matched that". That is the screenshot.
     *
     * The rest is what was asked for on top of it: the results grouped
     * by the person who made them, the artist and the album clickable so
     * you can walk into them, and a query that keeps its footing — when
     * the whole phrase finds nothing it falls back to the longest part
     * of it that finds something, and says which part that was, rather
     * than going blank on a typo. */
    const rowsOf = (got) => {
      if (!got) return [];
      if (Array.isArray(got)) return got;
      return got.results || got.tracks || got.rows || got.items || [];
    };
    const draw = (rows, said) => {
      list.textContent = "";
      if (said) {
        const n = mk("div", "wk-note", said);
        n.style.cssText = "font-size:9px;opacity:.7;margin-bottom:4px";
        list.appendChild(n);
      }
      const use = (rows || []).slice(0, 60);
      if (!use.length) {
        list.appendChild(mk("div", "wk-note",
                            "nothing in the library matched that"));
        return;
      }
      /* Grouped by artist, in the order they first appear, so a search
       * for a person reads as that person's shelf rather than a flat
       * list of tracks that happen to share a word. */
      const order = [];
      const by = {};
      use.forEach((t) => {
        const who = String(t.artist || "unknown");
        if (!by[who]) { by[who] = []; order.push(who); }
        by[who].push(t);
      });
      order.forEach((who) => {
        const head = mk("div", "");
        head.style.cssText = "display:flex;align-items:center;gap:6px;"
          + "margin:5px 0 2px";
        const nm = mk("b", "", who);
        nm.style.cssText = "flex:1 1 auto;min-width:0;color:#7ce8a9;"
          + "font-size:10px;cursor:pointer;overflow:hidden;"
          + "text-overflow:ellipsis;white-space:nowrap";
        nm.title = "Search the library for everything by " + who;
        nm.onclick = () => { box.value = who; hunt(true); };
        head.appendChild(nm);
        const count = mk("span", "wk-note", by[who].length + "");
        count.style.cssText = "flex:0 0 auto;font-size:9px;opacity:.55";
        head.appendChild(count);
        list.appendChild(head);
        by[who].forEach((t) => {
          const b = mk("button", "", "");
          b.style.cssText = "display:flex;align-items:center;gap:6px;"
            + "width:100%;text-align:left;font-size:10px;padding:3px 6px;"
            + "margin-bottom:2px;white-space:normal;line-height:1.4;"
            + "height:auto";
          if (t.art) {
            const im = mk("img", "");
            im.src = desktopMusicUrl(t.art);
            im.loading = "lazy";
            im.style.cssText = "width:22px;height:22px;border-radius:4px;"
              + "object-fit:cover;flex:0 0 auto";
            im.onerror = () => { im.style.display = "none"; };
            b.appendChild(im);
          }
          const words = mk("span", "", "");
          words.style.cssText = "flex:1 1 auto;min-width:0";
          words.appendChild(mk("div", "", String(t.title || t.id)));
          if (t.album) {
            const al = mk("div", "wk-note", t.album
              + (t.seconds ? " \u00b7 " + Math.round(t.seconds / 60)
                             + ":" + String(Math.round(t.seconds % 60))
                               .padStart(2, "0") : ""));
            al.style.cssText = "font-size:8.5px;opacity:.6";
            words.appendChild(al);
          }
          b.appendChild(words);
          b.onclick = () => pin(t.id, ((t.artist ? t.artist + " - " : "")
                                       + (t.title || "")));
          list.appendChild(b);
          if (t.album) {
            // Right-click walks into the album; a left click is already
            // spoken for by pinning the track.
            b.title = "Click to pin · right-click to open “"
              + t.album + "”";
            b.oncontextmenu = (ev) => {
              ev.preventDefault();
              box.value = t.album;
              hunt(true);
            };
          }
        });
      });
    };
    let timer = 0;
    let seq = 0;
    /* The library is asked for the whole phrase first; if that comes
     * back empty, for the phrase minus its last word, and so on down to
     * the first word. The first thing that answers is what is shown. */
    const tries = (q) => {
      const bits = q.split(/\s+/).filter(Boolean);
      const out = [];
      for (let i = bits.length; i > 0; i -= 1) out.push(bits.slice(0, i).join(" "));
      return out.length ? out : [""];
    };
    const hunt = async (now) => {
      const me = ++seq;
      const q = String(box.value || "").trim();
      list.dataset.busy = "1";
      if (!q) {
        try {
          const got = await api.get("/api/music/browse?limit=40");
          if (me === seq) draw(rowsOf(got), "everything in the library");
        } catch (e) {
          if (me === seq) list.textContent = "the library is unreachable";
        }
        return;
      }
      const ladder = tries(q);
      for (let i = 0; i < ladder.length; i += 1) {
        let got = null;
        try {
          got = await api.get("/api/music/search?q="
                              + encodeURIComponent(ladder[i]) + "&limit=60");
        } catch (e) {
          if (me === seq) list.textContent = "the library is unreachable";
          return;
        }
        if (me !== seq) return;             // a newer keystroke won
        const rows = rowsOf(got);
        if (rows.length) {
          draw(rows, i === 0
            ? rows.length + " in the library for \u201c" + q + "\u201d"
            : "nothing for \u201c" + q + "\u201d \u2014 showing \u201c"
              + ladder[i] + "\u201d instead");
          return;
        }
      }
      if (me === seq) draw([], "");
      void now;
    };
    box.oninput = () => { clearTimeout(timer); timer = setTimeout(hunt, 180); };
    hunt();
    document.body.appendChild(d);
    try { pvFloatDesk(d); } catch (e) {}
    box.focus();
  }

  /* #909/#897/#906 — THE PROMPT DESK for one entry of the hour.
   *
   * "When I click these, pop up a pop-up window allowing me to edit and
   * adjust them and be able to save to preferences the modified system
   * prompts... and I want to be able to jump between them and select
   * which system prompts are being used based on the ones that we have
   * saved."
   *
   * One window, two doors into it. The 📝 door edits the prompt this
   * entry AIRS with; the ✎ door on the stacked drawer edits the prompt
   * the next candidate is WRITTEN with and pins what comes back as the
   * stand-in. Both read the same /api/schedule/segment/prompt, so what
   * is in the box is what the writing room is actually handed - never a
   * reconstruction of it.
   */
  function promptDesk(slot, i, opts) {
    const how = opts || {};
    const old = document.getElementById("worksPromptDesk");
    if (old) old.remove();
    const d = mk("div", "works-pop");
    d.id = "worksPromptDesk";
    const r = pop.getBoundingClientRect();
    d.style.cssText = "position:fixed;z-index:404;width:min(520px,52vw);"
      + "max-height:84vh;overflow:auto;left:"
      + Math.max(8, Math.round(r.left - 100)) + "px;top:"
      + Math.round(r.top + 26) + "px";
    d.onclick = (e) => e.stopPropagation();

    const h = mk("div", "wk-head");
    h.appendChild(mk("b", "", (how.generate ? "\u270e " : "\ud83d\udcdd ")
      + (slot.label || slot.kind)));
    const cx = mk("button", "wk-x", "\u2715");
    cx.onclick = () => d.remove();
    h.appendChild(cx);
    d.appendChild(h);

    d.appendChild(mk("div", "wk-sub",
      hour.label + " on " + hour.date + " \u00b7 "
      + (how.generate
         ? "this is the system prompt the next candidate is WRITTEN with"
         : "this is the system prompt this entry goes on air with")));

    const say = mk("div", "wk-note", "reading\u2026");
    say.style.cssText = "font-size:9.5px;margin:4px 0 2px;opacity:.8";
    d.appendChild(say);
    const noteRow = mk("div", "wk-note", "");
    noteRow.style.cssText = "font-size:9px;opacity:.6;margin-bottom:4px";
    d.appendChild(noteRow);

    /* THE LIBRARY. One click drops a saved prompt into the box below,
     * which is what "jump between them" means from this end. */
    d.appendChild(mk("div", "wk-note", "SAVED PROMPTS FOR THIS KIND"));
    const shelf = mk("div", "");
    shelf.style.cssText = "max-height:152px;overflow:auto;margin:2px 0 6px";
    d.appendChild(shelf);

    d.appendChild(mk("div", "wk-note", "THE SYSTEM PROMPT"));
    const ta = mk("textarea", "");
    ta.style.cssText = "width:100%;height:170px;font-size:10.5px;"
      + "font-family:ui-monospace,Consolas,monospace";
    d.appendChild(ta);

    /* STORE IT. A name AND the scenario it suits, because that is the
     * whole point of a library: you find it again by what it was FOR. */
    const keep = mk("div", "");
    keep.style.cssText = "display:flex;gap:4px;margin-top:5px";
    const nameIn = mk("input", "");
    nameIn.placeholder = "name it\u2026";
    nameIn.style.cssText = "flex:1;min-width:0;font-size:10.5px";
    const whenIn = mk("input", "");
    whenIn.placeholder = "the scenario it suits\u2026";
    whenIn.style.cssText = "flex:1.3;min-width:0;font-size:10.5px";
    const keepB = mk("button", "", "\ud83d\udcbe save to the book");
    keepB.style.cssText = "font-size:10px;padding:2px 7px;white-space:nowrap";
    keep.appendChild(nameIn);
    keep.appendChild(whenIn);
    keep.appendChild(keepB);
    d.appendChild(keep);

    d.appendChild(mk("div", "wk-note", "PUT IT TO WORK"));
    const acts = mk("div", "");
    acts.style.cssText = "display:flex;flex-wrap:wrap;gap:5px;margin-top:3px";
    d.appendChild(acts);
    const note = mk("div", "wk-note", "");
    note.style.cssText = "font-size:9.5px;margin-top:6px;min-height:12px;"
      + "line-height:1.45";
    d.appendChild(note);

    let editing = null;        // the saved prompt being rewritten, if any
    let first = true;

    const drawBook = (rows, windows) => {
      shelf.textContent = "";
      (rows || []).slice(0, 40).forEach((row2) => {
        const it = mk("div", "");
        it.style.cssText = "display:flex;gap:4px;align-items:center;"
          + "border:1px solid #24384a;border-radius:6px;padding:3px 5px;"
          + "margin-bottom:3px;background:rgba(255,255,255,.02)";
        const nm = mk("span", "", String(row2.name || "untitled"));
        nm.style.cssText = "flex:1;min-width:0;overflow:hidden;"
          + "text-overflow:ellipsis;white-space:nowrap;font-size:10px;"
          + "color:#9fd8ff";
        nm.title = String(row2.text || "").slice(0, 400);
        it.appendChild(nm);
        if (row2.scenario) {
          const sc = mk("span", "wk-note", String(row2.scenario));
          sc.style.cssText = "flex:1.1;min-width:0;overflow:hidden;"
            + "text-overflow:ellipsis;white-space:nowrap;font-size:9px;"
            + "opacity:.65";
          it.appendChild(sc);
        }
        const use = mk("button", "", "open");
        use.title = "Put these words in the box below";
        use.style.cssText = "font-size:9px;padding:1px 6px";
        use.onclick = () => {
          ta.value = String(row2.text || "");
          nameIn.value = String(row2.name || "");
          whenIn.value = String(row2.scenario || "");
          editing = row2;
          note.style.color = "";
          note.textContent = "editing \u201c" + (row2.name || "")
            + "\u201d \u2014 saving under the same name rewrites it, "
            + "under a new name stores another";
        };
        it.appendChild(use);
        const del = mk("button", "", "\u2715");
        del.title = "Take it out of the book (nothing on air changes)";
        del.style.cssText = "font-size:9px;padding:1px 5px";
        del.onclick = async () => {
          try {
            await api.del("/api/schedule/promptbook/"
                          + encodeURIComponent(row2.id));
          } catch (e) { /* the shelf redraws either way */ }
          if (editing && editing.id === row2.id) editing = null;
          refresh();
        };
        it.appendChild(del);
        shelf.appendChild(it);
      });
      if (!(rows || []).length) {
        const none = mk("div", "wk-note",
          "nothing saved for this kind yet \u2014 write one below, name "
          + "it, and it is here for every " + (slot.kind || "segment")
          + " entry from now on");
        none.style.cssText = "font-size:9px;opacity:.6";
        shelf.appendChild(none);
      }
      /* #906: a timed prompt holding this kind says so, with its clock
       * running and the way to stop it early. */
      const w = (windows || {})[slot.kind];
      if (w) {
        const wr = mk("div", "");
        wr.style.cssText = "display:flex;gap:5px;align-items:center;"
          + "border:1px solid rgba(124,232,169,.5);border-radius:6px;"
          + "padding:3px 6px;margin-top:4px;"
          + "background:rgba(124,232,169,.08)";
        const wt = mk("span", "", "\u23f1 \u201c" + (w.name || "a prompt")
          + "\u201d owns every " + slot.kind + " entry \u00b7 "
          + (w.says || "") + " \u00b7 "
          + Math.max(0, Math.round(w.minutes_left || 0)) + "m left");
        wt.style.cssText = "flex:1;min-width:0;font-size:9px;color:#7ce8a9;"
          + "line-height:1.4";
        wr.appendChild(wt);
        const stop = mk("button", "", "stop it");
        stop.title = "Back to this entry's own standing instruction, now";
        stop.style.cssText = "font-size:9px;padding:1px 6px";
        stop.onclick = async () => {
          try {
            await api.del("/api/schedule/promptbook/window/"
                          + encodeURIComponent(slot.kind));
          } catch (e) { /* the banner redraws either way */ }
          refresh();
        };
        wr.appendChild(stop);
        shelf.appendChild(wr);
      }
    };

    const refresh = async () => {
      let got = null;
      try {
        got = await api.get("/api/schedule/segment/prompt?hour="
          + encodeURIComponent(hour.key) + "&slot="
          + encodeURIComponent(slot.id || "") + "&kind="
          + encodeURIComponent(slot.kind || ""));
      } catch (e) {
        say.textContent = "the prompt desk is not available";
        return;
      }
      say.textContent = "writing with: " + (got.source || "\u2014")
        + ((got.variant && got.variant.name)
           ? " \u00b7 \u201c" + got.variant.name + "\u201d" : "");
      noteRow.textContent = got.notes
        ? "the working note on this entry: " + got.notes : "";
      /* The box is filled ONCE. A refresh while the operator is typing
       * must never take the words out from under him. */
      if (first) {
        first = false;
        ta.value = String(got.text || got.seed || "");
        ta.placeholder = String(got.seed || "");
      }
      drawBook(got.book, got.windows);
    };

    /* Every action button behaves the same: it says what it did, or that
     * the desk refused it, and never leaves itself stuck disabled. */
    const button = (txt, title, fn) => {
      const b = mk("button", "", txt);
      b.title = title;
      b.style.cssText = "font-size:10px;padding:2px 8px";
      b.onclick = async () => {
        const was = b.textContent;
        b.disabled = true;
        b.textContent = "\u2026";
        try {
          const msg = await fn();
          note.style.color = "#7ce8a9";
          note.textContent = msg || "done";
        } catch (e) {
          note.style.color = "#e88c8c";
          note.textContent = "the desk refused that";
        }
        b.textContent = was;
        b.disabled = false;
        refresh();
      };
      acts.appendChild(b);
      return b;
    };

    const apply = (scope, minutes) => api.post(
      "/api/schedule/promptbook/apply",
      {scope: scope, text: ta.value, name: nameIn.value || "",
       hour: hour.key, slot: slot.id || "", kind: slot.kind || "",
       minutes: minutes || 0, id: editing ? editing.id : ""});

    if (how.generate) {
      /* #897: send the edited brief back up, and what comes back is the
       * stand-in for this position this hour. */
      button("\u270e write another with this prompt",
             "Write a new candidate using exactly these words, and pin "
             + "what comes back as the stand-in for this entry this hour",
             async () => {
               await api.post("/api/schedule/segment/generate",
                 {hour: hour.key, slot: slot.id, count: 1,
                  prompt: ta.value, pin: true,
                  save_as: nameIn.value || ""});
               if (typeof how.after === "function") {
                 setTimeout(how.after, 4000);
               }
               return "the desk is on it \u2014 what comes back is pinned "
                 + "to this entry as the stand-in for " + hour.label;
             });
    }

    button("this entry, this hour",
           "Script this entry for " + hour.label + " and nothing else",
           async () => {
             await api.post("/api/schedule/hours/"
                            + encodeURIComponent(hour.key) + "/prompt",
                            {slot_id: slot.id, text: ta.value,
                             name: nameIn.value
                                   || (hour.label + " "
                                       + (slot.label || slot.kind))});
             load();
             return "this entry runs it at " + hour.label
               + " \u2014 that hour only";
           });
    button("\u2605 make it the default",
           "This entry writes with it from now on \u2014 a permanent "
           + "change to the running order",
           async () => {
             await apply("default");
             return "it is this entry's standing instruction from now on";
           });
    button("\u25b6 the next segment",
           "The very next " + (slot.kind || "") + " segment writes with "
           + "it, then it lets go by itself",
           async () => {
             await apply("next_segment");
             return "the next " + (slot.kind || "") + " segment runs it, "
               + "then everything is back to normal";
           });
    button("\u23f1 the next 30 minutes",
           "Every " + (slot.kind || "") + " entry in the next half hour",
           async () => {
             await apply("next_30", 30);
             return "every " + (slot.kind || "") + " entry for the next "
               + "thirty minutes runs it";
           });
    button("\u23f1\u23f1 the next hour",
           "Both thirty-minute halves \u2014 every " + (slot.kind || "")
           + " entry for the next sixty minutes",
           async () => {
             await apply("next_hour");
             return "it runs for the next thirty minutes and then for the "
               + "thirty minutes after that";
           });

    keepB.onclick = async () => {
      keepB.disabled = true;
      try {
        await api.post("/api/schedule/promptbook",
          {id: (editing && nameIn.value === editing.name) ? editing.id : "",
           name: nameIn.value || (slot.label || slot.kind),
           kind: slot.kind || "",
           scenario: whenIn.value || "",
           text: ta.value});
        note.style.color = "#7ce8a9";
        note.textContent = "saved to the book \u2014 it is on the shelf "
          + "above for every " + (slot.kind || "segment") + " entry now";
        editing = null;
      } catch (e) {
        note.style.color = "#e88c8c";
        note.textContent = "that would not save";
      }
      keepB.disabled = false;
      refresh();
    };

    document.body.appendChild(d);
    try { pvFloatDesk(d); } catch (e) { /* it is still on screen */ }
    refresh();
  }

  function detail(slot, i) {
    const old = document.getElementById("worksSchedDetail");
    if (old) old.remove();
    const d = mk("div", "works-pop");
    d.id = "worksSchedDetail";
    const r = pop.getBoundingClientRect();
    d.style.cssText = "position:fixed;z-index:402;width:min(420px,44vw);"
      + "max-height:70vh;overflow:auto;left:"
      + Math.max(8, Math.round(r.left - 30)) + "px;top:"
      + Math.round(r.top + 60) + "px";
    d.onclick = (e) => e.stopPropagation();
    const h = mk("div", "wk-head");
    h.appendChild(mk("b", "", (SCHED_ICON[slot.kind] || "•") + " "
                              + (slot.label || slot.kind)));
    const cx = mk("button", "wk-x", "✕");
    cx.onclick = () => d.remove();
    h.appendChild(cx);
    d.appendChild(h);
    d.appendChild(mk("div", "wk-sub",
      hour.label + " on " + hour.date + " · starts " + slot.starts_at
      + " · this hour only"));

    const nameIn = mk("input", "");
    nameIn.value = slot.label || "";
    nameIn.style.cssText = "width:100%;font-size:11px;margin:6px 0 4px";
    d.appendChild(mk("div", "wk-note", "WHAT IT IS CALLED"));
    d.appendChild(nameIn);

    const minIn = mk("input", "");
    minIn.type = "number"; minIn.min = "0.25"; minIn.step = "0.25";
    minIn.value = String(slot.minutes);
    minIn.style.cssText = "width:90px;font-size:11px;margin-bottom:4px";
    d.appendChild(mk("div", "wk-note", "MINUTES OF THE HOUR"));
    d.appendChild(minIn);

    d.appendChild(mk("div", "wk-note", "THE SYSTEM PROMPT FOR THIS ENTRY"));
    const ta = mk("textarea", "");
    ta.style.cssText = "width:100%;height:150px;font-size:10.5px;"
      + "font-family:ui-monospace,Consolas,monospace";
    ta.placeholder = "Leave empty to use whatever is armed for a "
      + slot.kind + " round.";
    d.appendChild(ta);
    api.get("/api/schedule/prompts").then((pr) => {
      const band = (pr || {})[slot.kind] || {};
      const vs = band.variants || [];
      const pinned = vs.filter((v) => v.id === slot.prompt_id)[0];
      const armed = vs[band.active || 0];
      ta.value = (pinned || armed || {}).text || "";
    }).catch(() => {});

    /* #909/#906: the box above scripts THIS hour and nothing else. The
     * book is where a prompt gets a name, gets kept, and gets handed a
     * window of air - so the door to it is right here beside it. */
    const bookB = mk("button", "",
                     "\ud83d\udcdd the prompt book \u00b7 save, swap, "
                     + "and how long it runs\u2026");
    bookB.style.cssText = "font-size:10px;margin-top:5px;padding:2px 7px";
    bookB.onclick = (ev) => { ev.stopPropagation(); promptDesk(slot, i, {}); };
    d.appendChild(bookB);

    const acts = mk("div", "wk-note", "");
    acts.style.cssText = "display:flex;gap:6px;margin-top:6px";
    const saven = mk("button", "", "save for this hour");
    saven.style.cssText = "font-size:10.5px;padding:2px 8px;font-weight:700";
    saven.onclick = async () => {
      saven.textContent = "saving…";
      const list = hour.slots.map((r2, j) => j === i
        ? Object.assign({}, r2, {label: nameIn.value,
                                 minutes: Number(minIn.value) || r2.minutes})
        : r2);
      hour.slots = list;
      await save(list);
      if (String(ta.value || "").trim()) {
        try {
          await api.post("/api/schedule/hours/"
                         + encodeURIComponent(hour.key) + "/prompt",
                         {slot_id: slot.id, text: ta.value,
                          name: hour.label + " " + (slot.label || slot.kind)});
        } catch (e) {}
      }
      d.remove();
      load();
    };
    acts.appendChild(saven);
    d.appendChild(acts);
    document.body.appendChild(d);
    try { pvFloatDesk(d); } catch (e) {}
  }

  async function load() {
    try {
      const from = offset ? hourKeyAhead(offset) : "";
      const got = await api.get("/api/schedule/hours?count=1"
                                + (from ? "&from=" + encodeURIComponent(from) : ""));
      hour = ((got && got.hours) || [])[0] || null;
      paint();
    } catch (e) {
      body.textContent = "";
      body.appendChild(mk("div", "wk-note",
        "the hour sheet is not available yet"));
    }
  }

  function hourKeyAhead(n) {
    const d = new Date();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + n);
    const p = (v) => String(v).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
           + "T" + p(d.getHours());
  }

  /* #920: n hours on from a NAMED hour rather than from now - what
   * "schedule this one forward" needs. Built through a real Date so the
   * clocks changing cannot hand the panel an hour that does not exist,
   * exactly as _sched_hour_shift does at the other end. */
  function hourKeyFrom(key, n) {
    const bits = String(key || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})$/);
    const d = bits
      ? new Date(Number(bits[1]), Number(bits[2]) - 1, Number(bits[3]),
                 Number(bits[4]), 0, 0, 0)
      : new Date();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + (Number(n) || 0));
    const p = (v) => String(v).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
           + "T" + p(d.getHours());
  }

  /* #920: "Allow me to scroll back to previous half hour stretches."
   * The ‹ button clamped at the hour on air, so there was nothing behind
   * it to reach at all - which is the whole of what the operator was
   * clicking in the screenshot. Twelve hours back is as far as it goes:
   * the RECORDINGS only survive two of them, and past that the tiles are
   * there to be read and copied forward, which is the other half of what
   * was asked for. The five-second reload still only follows the hour on
   * air, so a past sheet you are reading holds still. */
  prev.onclick = () => { offset = Math.max(-12, offset - 1); load(); };
  next.onclick = () => { offset = Math.min(72, offset + 1); load(); };
  /* #986: "If I double click this, jump back to the active hour."
   *
   * The arrows walk twelve hours back and seventy-two forward, so it is
   * easy to end up a long way from the hour that is actually on air and
   * a nuisance to click your way home. Double-clicking the hour label
   * puts the cursor back on now. Single click is left alone - the label
   * sits between the two arrows and a stray click should not move you. */
  label.title = "Double-click to jump back to the hour on air";
  label.style.cursor = "pointer";
  label.ondblclick = () => {
    if (!offset) return;                  // already home
    offset = 0;
    load();
  };
  load();
  const tick = setInterval(() => { if (!offset) load(); }, 5000);
}

/* #885: one entry on the writing desk. Its own triangle, its own memory
 * of whether it is open, and it is built once and never touched again. */
function wkDeskEntry(id, c) {
  const mk2 = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const key = "desk:" + id;
  const open = wkDeskOpen(key);
  const t = mk2("div", "wkDeskEntry");
  t.wkId = id;
  t.wkKey = key;
  t.style.cssText = "border-left:2px solid #3f7fa8;padding-left:7px;"
    + "margin:6px 0";
  const label = (c.kind || "a round") + " \u00b7 " + (c.ms || 0)
    + " ms \u00b7 " + (c.chars || 0) + " chars \u00b7 ctx "
    + (c.num_ctx || "?") + " \u00b7 temp "
    + (c.temp != null ? c.temp : "?");
  t.wkLabel = label;
  const nm = mk2("div", "");
  nm.style.cssText = "font-size:10.5px;font-weight:700;color:#9fd8ff;"
    + "cursor:pointer;user-select:none";
  nm.textContent = (open ? "\u25be " : "\u25b8 ") + label;
  nm.title = "Click to open this call \u2014 the prompt as sent, "
    + "what was governing it, and the script that came back";
  t.wkHead = nm;
  t.appendChild(nm);
  /* #984: A ROW SAYS SOMETHING WHEN IT IS SHUT.
   *
   * The desk holds forty calls and every one of them read as the
   * same sentence - a kind, a duration, a character count - so
   * finding the call you actually wanted meant opening them one at
   * a time. The first line of what came back is the one thing that
   * tells them apart at a glance, and it costs nothing: the payload
   * already carries it. */
  const peek = mk2("div", "");
  peek.style.cssText = "font-size:9.5px;line-height:1.45;opacity:.62;"
    + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
    + "cursor:pointer;margin-top:1px";
  const said = String(c.script || c.text || "")
    .replace(/\s+/g, " ").trim();
  peek.textContent = said ? said.slice(0, 150) : "(nothing came back)";
  peek.title = said.slice(0, 400);
  peek.style.display = open ? "none" : "block";
  t.wkPeek = peek;
  t.appendChild(peek);
  const inner = mk2("div", "");
  inner.style.display = open ? "block" : "none";
  t.wkInner = inner;
  try {
    wkPutInto(inner, "GOVERNED BY",
      (c.armed ? "system prompt: " + c.armed : "")
      + (c.sched ? (c.armed ? "\n\n" : "") + c.sched : ""));
    wkPutInto(inner, "WHAT WE SENT", c.prompt, true);
    wkPutInto(inner, "WHAT CAME BACK", c.script || c.text, true);
  } catch (e) { /* an entry with no paperwork still lists */ }
  t.appendChild(inner);
  const flip = (ev) => {
    ev.stopPropagation();
    wkDeskFold(t, !wkDeskOpen(key));
  };
  nm.onclick = flip;
  peek.onclick = flip;      // #984: the whole row opens, not just the name
  return t;
}

/* Open unless it has been folded away: a fresh call arrives open, the way
 * it always did, and only the ones you CLOSE are remembered - so this
 * never grows. It is kept apart from wkOpen, which the five stages own
 * and rewrite wholesale. */
function wkDeskShut() {
  try { return JSON.parse(localStorage.getItem("wkDeskShut") || "{}") || {}; }
  catch (e) { return {}; }
}

/* #964: the reserve remembers which rounds you OPENED, where the desk
 * remembers which ones you SHUT. Same mechanism, opposite default,
 * because the desk holds a handful of calls and the reserve holds the
 * whole night's rounds. */
/* #987: everything behind one banked round in one window - what it is
 * for, the system prompt that was armed, the schedule's own instruction,
 * the prompt as sent, and what came back. Empty sections are left out
 * rather than shown as blanks. */
function wkRoundPaper(r) {
  const gone = document.getElementById("wkRoundPaper");
  if (gone) gone.remove();
  const d = document.createElement("div");
  d.id = "wkRoundPaper";
  d.style.cssText = "position:fixed;left:50%;top:50%;"
    + "transform:translate(-50%,-50%);width:min(760px,94vw);max-height:86vh;"
    + "overflow:auto;z-index:300;background:#070c12;border:1px solid #24384a;"
    + "border-radius:10px;padding:12px 14px;box-shadow:0 20px 60px #000c";
  const head = document.createElement("div");
  head.style.cssText = "display:flex;gap:8px;align-items:baseline;margin-bottom:8px";
  const h = document.createElement("b");
  h.textContent = "how this round was written";
  h.style.cssText = "flex:1;font-size:13px;color:#9fd8ff";
  const x = document.createElement("button");
  x.textContent = "\u2715";
  x.style.cssText = "font-size:11px;padding:2px 8px;cursor:pointer";
  x.onclick = () => d.remove();
  head.appendChild(h); head.appendChild(x);
  d.appendChild(head);
  const desk = r.desk || {};
  const chips = document.createElement("div");
  chips.style.cssText = "display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px";
  [["written for", r["for"] || "booth rounds"],
   ["model", desk.model || "\u2014"],
   ["took", desk.ms ? Math.round(desk.ms / 100) / 10 + "s" : "\u2014"],
   ["temperature", desk.temp == null ? "\u2014" : String(desk.temp)],
   ["context", desk.num_ctx ? String(desk.num_ctx) : "\u2014"]
  ].forEach((kv) => {
    const c = document.createElement("span");
    c.style.cssText = "background:#0e1826;border:1px solid #24435f;"
      + "border-radius:12px;padding:2px 9px;font-size:10px;color:#c8dcef";
    c.textContent = kv[0] + ": " + kv[1];
    chips.appendChild(c);
  });
  d.appendChild(chips);
  const part = (title, body) => {
    const text = String(body || "").trim();
    if (!text) return;
    const lab = document.createElement("div");
    lab.textContent = title;
    lab.style.cssText = "font-size:9px;letter-spacing:.06em;opacity:.75;"
      + "margin:8px 0 3px;color:#7fb0c9";
    d.appendChild(lab);
    const pre = document.createElement("pre");
    pre.textContent = text;
    pre.style.cssText = "white-space:pre-wrap;word-break:break-word;"
      + "font-size:10.5px;line-height:1.5;margin:0;padding:7px 9px;"
      + "background:#05090f;border:1px solid #1b2c3c;border-radius:6px;"
      + "max-height:34vh;overflow:auto;color:#c8d6e4";
    d.appendChild(pre);
  };
  part("THE SYSTEM PROMPT THAT WAS ARMED", desk.armed);
  part("WHAT THE SCHEDULE ASKED FOR", desk.sched);
  part("THE PROMPT AS SENT", desk.prompt);
  part("WHAT CAME BACK", desk.script || r.script);
  if (!desk.prompt && !desk.armed) {
    const none = document.createElement("div");
    none.style.cssText = "font-size:10px;opacity:.6;margin-top:6px";
    none.textContent = "This round was banked before its paperwork was kept "
      + "with it, so only the script survives.";
    d.appendChild(none);
  }
  document.body.appendChild(d);
  try { pvFloatDesk(d); } catch (e) {}
}

/* #992: rewrite a banked round by hand and send it back to be cut. */
function wkRoundEdit(r) {
  const gone = document.getElementById("wkRoundEdit");
  if (gone) gone.remove();
  const d = document.createElement("div");
  d.id = "wkRoundEdit";
  d.style.cssText = "position:fixed;left:50%;top:50%;"
    + "transform:translate(-50%,-50%);width:min(760px,94vw);z-index:300;"
    + "background:#070c12;border:1px solid #24384a;border-radius:10px;"
    + "padding:12px 14px;box-shadow:0 20px 60px #000c;display:flex;"
    + "flex-direction:column;gap:8px";
  const h = document.createElement("b");
  h.textContent = "rewrite this " + (r["for"] || "round");
  h.style.cssText = "font-size:13px;color:#9fd8ff";
  d.appendChild(h);
  const note = document.createElement("div");
  note.style.cssText = "font-size:10px;opacity:.7;line-height:1.5";
  note.textContent = "Saving gives up the audio already cut for this round "
    + "and sends it back to the recording room to be made again in your "
    + "words. The model is not asked to rewrite them.";
  d.appendChild(note);
  const ta = document.createElement("textarea");
  ta.value = String(r.script || "");
  ta.style.cssText = "width:100%;min-height:44vh;font-size:11px;"
    + "line-height:1.55;background:#05090f;color:#dbe6f0;border:1px solid "
    + "#1b2c3c;border-radius:6px;padding:8px 10px;resize:vertical";
  d.appendChild(ta);
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:6px;align-items:center";
  const status = document.createElement("span");
  status.style.cssText = "flex:1;font-size:10px;opacity:.75";
  const save = document.createElement("button");
  save.textContent = "\u21b3 send it back to be recorded";
  save.style.cssText = "font-size:10px;padding:4px 10px;cursor:pointer";
  save.onclick = async () => {
    save.disabled = true;
    status.textContent = "sending\u2026";
    try {
      await api.post("/api/dj/pending/" + encodeURIComponent(r.id) + "/script",
                     {script: ta.value});
      status.textContent = "sent \u2014 it will be cut again shortly";
      setTimeout(() => d.remove(), 900);
    } catch (err) {
      status.textContent = err.message;
      save.disabled = false;
    }
  };
  const shut = document.createElement("button");
  shut.textContent = "cancel";
  shut.style.cssText = "font-size:10px;padding:4px 10px;cursor:pointer";
  shut.onclick = () => d.remove();
  row.appendChild(status); row.appendChild(shut); row.appendChild(save);
  d.appendChild(row);
  document.body.appendChild(d);
  try { pvFloatDesk(d); } catch (e) {}
}

function wkResShown() {
  try {
    const raw = localStorage.getItem("wkResOpen");
    const all = raw ? JSON.parse(raw) : {};
    return all && typeof all === "object" ? all : {};
  } catch (e) { return {}; }
}

function wkResOpen(key) {
  try { return wkResShown()[key] === true; } catch (e) { return false; }
}

function wkResFold(key, want) {
  try {
    const all = wkResShown();
    if (want) all[key] = true; else delete all[key];
    localStorage.setItem("wkResOpen", JSON.stringify(all));
  } catch (e) { /* private mode: it still folds for this session */ }
}

function wkDeskOpen(key) {
  try { return wkDeskShut()[key] !== true; } catch (e) { return true; }
}

function wkDeskFold(t, want) {
  try {
    if (!t || !t.wkKey) return;
    const all = wkDeskShut();
    if (want) delete all[t.wkKey];
    else all[t.wkKey] = true;
    try { localStorage.setItem("wkDeskShut", JSON.stringify(all)); }
    catch (e) { /* private mode: it still works for this session */ }
    t.wkHead.textContent = (want ? "\u25be " : "\u25b8 ") + t.wkLabel;
    t.wkInner.style.display = want ? "block" : "none";
    // #984: the preview IS the closed state's content, so it steps
    // aside when the real thing arrives.
    if (t.wkPeek) t.wkPeek.style.display = want ? "none" : "block";
  } catch (e) { /* one stubborn entry is not worth the drawer */ }
}

/* A call that has aged off the bottom takes its memory with it. */
function wkDeskForget(id) {
  try {
    if (!id) return;
    const all = wkDeskShut();
    if (all["desk:" + id] === undefined) return;
    delete all["desk:" + id];
    localStorage.setItem("wkDeskShut", JSON.stringify(all));
  } catch (e) { /* nothing here is worth the drawer */ }
}

/* One labelled block inside an entry - the same look as wkPut. */
function wkPutInto(box, label, text, mono) {
  if (!text) return;
  const h = document.createElement("div");
  h.className = "wk-note";
  h.textContent = label;
  h.style.cssText = "font-size:9px;letter-spacing:.05em;margin:6px 0 2px;"
    + "opacity:.8";
  box.appendChild(h);
  const b = document.createElement("div");
  b.textContent = String(text);
  b.style.cssText = "font-size:10px;line-height:1.5;white-space:pre-wrap;"
    + "max-height:26vh;overflow:auto;padding:5px 7px;border-radius:6px;"
    + "background:#05090f;border:1px solid #24384a"
    + (mono ? ";font-family:ui-monospace,Consolas,monospace" : "");
  box.appendChild(b);
}

/* #939: THE TAPE CONTROLS for one prepared section — play the welded
 * whole, keep it, or open the transcript and take any single line.
 * Deliberately module-level: the kind drawers live inside The Works and
 * the hour sheet is its own function, and both want the same three
 * buttons. Everything is built lazily — a transcript is only fetched
 * when its tick is opened, and a section is only welded when ▶ or ⬇ is
 * actually pressed, because welding twenty clips is seconds of work. */
/* #898/#902: SAVE, rather than "open it somewhere else". Every keep in
 * the works called api.openExternal, which hands the signed URL to the
 * system browser - the operator asked to DOWNLOAD the clip. Fetching it
 * and clicking a blob link puts it through Electron's own download
 * road, which opens the save dialog in the folder the last one went to
 * (#808) and reveals the file in File Explorer when it lands (#817). */
function wkFileName(bits, ext) {
  const clean = String(bits || "clip").replace(/[^\w \-]+/g, " ")
    .replace(/\s+/g, " ").trim();
  return (clean || "clip").slice(0, 60) + "." + (ext || "wav");
}

async function wkSaveBlob(url, name, btn) {
  const was = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "\u2026"; }
  try {
    /* #969: with the key on it. Signed /media links need nothing, but an
     * /api/... road goes through require_read_auth, and this helper is
     * used for both now — a bare fetch there comes back 401 and reads as
     * "could not save". The header is harmless when reads are open. */
    const head = {};
    try {
      if (config && config.apiKey) {
        head.Authorization = "Bearer " + config.apiKey;
      }
    } catch (e2) { /* no config yet */ }
    const r = await fetch(url, {headers: head});
    if (!r.ok) throw new Error("HTTP " + r.status);
    const blob = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = blob;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blob), 20000);
    if (btn) {
      btn.textContent = "saved";
      setTimeout(() => { btn.textContent = was; btn.disabled = false; },
                 2500);
    }
    return true;
  } catch (e) {
    if (btn) {
      btn.textContent = "could not save";
      setTimeout(() => { btn.textContent = was; btn.disabled = false; },
                 3000);
    }
    return false;
  }
}

function wkMediaUrl(row) {
  if (!row || !row.media || !row.sig) return "";
  return desktopMusicUrl("/media/" + encodeURIComponent(row.media)
                         + "?t=" + encodeURIComponent(row.sig));
}

/* #943: temperature, speakbox seeding, crystal tinting, chunks used —
 * and the dial that sends the whole thing back hotter. */
function wkStatStrip(host, kind, id, d) {
  const st = (d && d.stats) || {};
  const box = document.createElement("div");
  box.style.cssText = "border:1px solid #24384a;border-radius:6px;"
    + "padding:5px 7px;margin-bottom:5px;background:rgba(255,255,255,.02)";
  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:86px 1fr;"
    + "gap:2px 8px;font-size:9.5px;line-height:1.5";
  const row = (label, value, title) => {
    const dt = document.createElement("div");
    dt.textContent = label;
    dt.style.color = "#6d8199";
    const dd = document.createElement("div");
    dd.textContent = value;
    dd.style.color = "#c8d6e4";
    if (title) { dt.title = title; dd.title = title; }
    grid.appendChild(dt);
    grid.appendChild(dd);
  };

  const known = Object.keys(st).length > 0;
  if (!known) {
    const none = document.createElement("div");
    none.className = "wk-note";
    none.style.cssText = "font-size:9.5px;opacity:.6";
    /* Not "0" for each — four blanks read as "made with nothing" when
     * the truth is "nobody wrote it down at the time". */
    none.textContent = "this round was prepared before the working was "
      + "kept \u2014 its temperature, seed and tinting were not written "
      + "down at the time";
    box.appendChild(none);
  } else {
    const heat = Number(st.heat || 0);
    row("temperature",
        (st.temperature != null ? Number(st.temperature).toFixed(2)
                                : "\u2014")
        + (heat > 0.02 ? "  \u00b7  dial " + Math.round(heat * 100) + "%"
                       : "")
        + (st.model ? "  \u00b7  " + st.model : ""),
        "What this round was actually written at. The dial is #941's "
        + "heat: how hard this road was being pushed when it was "
        + "written, which rises with how many are already stacked "
        + "behind it.");
    row("speakbox",
        st.seed_file
          ? (st.seed_file + "  \u00b7  " + (st.seed_lines || 0)
             + " line(s), " + (st.seed_chars || 0) + " chars"
             + (st.seed_depth != null
                ? "  \u00b7  dug " + Math.round(Number(st.seed_depth) * 100)
                  + "%" : ""))
          : "no swath was drawn for this one",
        "Which document seeded it, how much of it came out, and how far "
        + "into the document the draw started (#895 — the deeper the "
        + "queue, the further in and the more obscure).");
    row("crystal",
        st.crystal ? (st.crystal + "  \u00b7  strength "
                      + (st.crystal_strength || 0) + "%"
                      + (st.crystal_mind ? "  \u00b7  " + st.crystal_mind
                                         : ""))
                   : "untinted \u2014 drawn from the studio library",
        "Whether a crystal was tinting the universe when this was "
        + "written, and which of its minds the material came from.");
    row("chunks",
        (st.chunks != null ? st.chunks : "\u2014") + " cut"
        + (st.made != null ? "  \u00b7  " + st.made + " recorded" : "")
        + (st.turns ? "  \u00b7  " + st.turns + " turns" : "")
        + (st.seconds ? "  \u00b7  " + Math.round(st.seconds) + "s" : ""),
        "How many separate takes the round was cut into, how many of "
        + "them have audio, and how long it runs.");
    if (st.regenerated_from) {
      row("came from", String(st.regenerated_from),
          "This one was written as a hotter version of another.");
    }
    if (st.operator_note) {
      row("your note", String(st.operator_note), "");
    }
    box.appendChild(grid);
  }

  /* The dial. */
  const dial = document.createElement("div");
  dial.style.cssText = "display:flex;gap:5px;align-items:center;"
    + "margin-top:5px;font-size:9px";
  const lab = document.createElement("span");
  lab.style.color = "#6d8199";
  lab.textContent = "insanity";
  dial.appendChild(lab);
  const rng = document.createElement("input");
  rng.type = "range";
  rng.min = "0";
  rng.max = "100";
  rng.value = "70";
  rng.style.cssText = "flex:1;min-width:70px;max-width:150px";
  dial.appendChild(rng);
  const val = document.createElement("span");
  val.style.cssText = "min-width:74px;color:#9fd8ff";
  const bands = (v) => (v < 34 ? "as written" : v < 55 ? "stranger"
                        : v < 78 ? "peculiar" : "unhinged");
  val.textContent = bands(70);
  rng.oninput = () => { val.textContent = bands(Number(rng.value)); };
  dial.appendChild(val);
  const go = document.createElement("button");
  go.textContent = "\ud83d\udd01 send it back";
  go.title = "Write another of this section down the same road, at this "
    + "dial, and stack it above the one it came from. The original is "
    + "left alone \u2014 bin it yourself once you have heard both.";
  go.className = wkBtnClass(go.textContent);              // #966
  go.onclick = async (ev) => {
    ev.stopPropagation();
    go.disabled = true;
    const was = go.textContent;
    go.textContent = "\u2026";
    try {
      await api.post("/api/shelf/regenerate",
                     {kind: kind, id: id,
                      insanity: Number(rng.value) / 100, promote: true});
      go.textContent = "the desk is on it";
    } catch (e) { go.textContent = "the desk refused that"; }
    setTimeout(() => { go.textContent = was; go.disabled = false; }, 5000);
  };
  dial.appendChild(go);
  box.appendChild(dial);
  host.appendChild(box);
}

function wkTapeBar(host, kind, id) {
  const bar = document.createElement("div");
  bar.className = "wk-actbar";                             // #966
  bar.style.marginTop = "3px";
  /* #966: a single glyph gets a square box; anything with words gets a
   * pill with the same padding on all four sides. The styling lives in
   * two CSS classes now rather than in a different inline rule per
   * button, which is how this row came to hold six different widths. */
  const mk2 = (txt, title) => {
    const b = document.createElement("button");
    b.textContent = txt;
    b.title = title;
    b.className = wkBtnClass(txt);
    bar.appendChild(b);
    return b;
  };
  const player = document.createElement("div");
  player.style.marginTop = "3px";

  let welded = null;
  const weld = async (btn, then) => {
    const was = btn.textContent;
    btn.disabled = true;
    btn.textContent = "welding\u2026";
    try {
      if (!welded) {
        welded = await api.get("/api/shelf/bundle?kind="
                               + encodeURIComponent(kind) + "&id="
                               + encodeURIComponent(id));
      }
      btn.textContent = was;
      btn.disabled = false;
      then(welded);
    } catch (e) {
      btn.textContent = (e && e.message && /409/.test(String(e.message)))
        ? "not recorded yet" : "could not weld";
      setTimeout(() => { btn.textContent = was; btn.disabled = false; }, 3000);
    }
  };

  mk2("\u25b6", "Play this whole section, welded end to end the way it "
                 + "would go out").onclick = (ev) => {
    ev.stopPropagation();
    weld(ev.target, (got) => {
      player.textContent = "";
      const au = document.createElement("audio");
      au.controls = true;
      au.autoplay = true;
      au.src = wkMediaUrl(got);
      au.style.cssText = "width:100%;height:26px";
      player.appendChild(au);
      const note = document.createElement("div");
      note.className = "wk-note";
      note.style.cssText = "font-size:9px;opacity:.6";
      note.textContent = got.lines + " lines \u00b7 "
        + Math.round(got.seconds) + "s \u00b7 "
        + Math.round((got.bytes || 0) / 1024) + " KB";
      player.appendChild(note);
    });
  };
  mk2("\u2b07", "Download this whole section as one file").onclick =
      (ev) => {
    ev.stopPropagation();
    const btn = ev.target;
    weld(btn, (got) => {
      /* #898: "allow me to download that full clip" - the welded whole,
       * saved to disk, not opened in a browser tab. */
      wkSaveBlob(wkMediaUrl(got),
                 wkFileName((got.label || kind) + " " + id, "wav"), btn);
    });
  };
  /* #902: and the whole review - the recording, every line of the
   * transcript playable on its own, where each one came from, and the
   * operator's own cut sent back through the writing and recording
   * rooms to be stacked on top. */
  mk2("\u25a4 review", "Open this section: play it, read every line, "
      + "hear any single phrase, see how it was written, and send your "
      + "own version back through the rooms").onclick = (ev) => {
    ev.stopPropagation();
    try { wkReviewPopup(kind, id); } catch (e) { /* the list still works */ }
  };

  const drw = document.createElement("div");
  drw.style.cssText = "display:none;margin:3px 0 2px 10px";
  const tri = mk2("\u25b8 transcript",
                  "Read every line of this section, and take any one of "
                  + "them on its own");
  tri.onclick = async (ev) => {
    ev.stopPropagation();
    const on = drw.style.display === "none";
    drw.style.display = on ? "block" : "none";
    tri.textContent = (on ? "\u25be" : "\u25b8") + " transcript";
    tri.className = wkBtnClass(tri.textContent);
    if (!on || drw.dataset.filled) return;
    drw.textContent = "reading the tape\u2026";
    let d = null;
    try {
      d = await api.get("/api/shelf/candidate?kind="
                        + encodeURIComponent(kind) + "&id="
                        + encodeURIComponent(id));
    } catch (e) {
      drw.textContent = "that section could not be read";
      return;
    }
    drw.dataset.filled = "1";
    drw.textContent = "";
    /* #943 (#941): the four figures, above the dialogue, in the order
     * they were asked for. */
    try { wkStatStrip(drw, kind, id, d); } catch (e) { /* the lines still show */ }
    const takes = d.lines || [];
    /* #959: THE CALLER GOES IN THE TRANSCRIPT.
     *
     * "This phone call doesn't show the person who called speaking at
     *  all, and the conversation doesn't actually make sense."
     *
     * `d.lines` is the list of PANTRY TAKES, and a caller has none by
     * design — their phone line is drawn once, live, inside speak_turns.
     * Listing the takes and calling it the transcript is why a banked
     * "Phone call" showed only Host and Skip talking about somebody who
     * was never there. The server sends the whole CAST now, in script
     * order, each row pointing at the takes made for it; the caller's
     * rows point at none and say so. Where there is no cast (an older
     * shelf row) this falls back to exactly what it did before. */
    const cast = (d.cast || []).length ? d.cast : null;
    const lines = cast
      ? cast.map((c) => {
          if (c.live) {
            return {who: c.who, name: c.name || "the caller", text: c.text,
                    recorded: false, live: true, seconds: 0};
          }
          const own = takes.slice(c.line_from, c.line_to);
          const first = own[0] || {};
          return Object.assign({}, first, {
            who: c.who,
            name: first.name || c.who,
            text: c.text,
            seconds: own.reduce((a, b) => a + (Number(b.seconds) || 0), 0),
            recorded: own.some((x) => x.recorded),
          });
        })
      : takes;
    const head = document.createElement("div");
    head.className = "wk-note";
    head.style.cssText = "font-size:9px;opacity:.65;margin-bottom:3px";
    const spoken = lines.filter((l) => l.live).length;
    head.textContent = lines.length + " line(s) \u00b7 "
      + lines.filter((l) => l.recorded).length + " recorded"
      + (spoken ? " \u00b7 " + spoken + " voiced live on the call" : "")
      + (d.derived ? " \u00b7 read back off the script" : "");
    head.title = d.derived
      ? "This round was prepared before the takes were written down, so "
        + "its lines are rederived exactly as the air road derives them."
      : "";
    drw.appendChild(head);
    /* And say so plainly when a phone call has nobody on the phone —
     * that is the fault, and counting Host rows by eye is how it went
     * unnoticed for so long. */
    if (cast && String(kind) === "caller") {
      const n = Number(d.caller_turns || 0);
      const flag = document.createElement("div");
      flag.style.cssText = "font-size:9px;line-height:1.5;margin-bottom:4px;"
        + "padding:4px 6px;border-radius:6px;border:1px solid "
        + (n ? "#2c5f43;background:#0c1a13;color:#9fe0bb"
             : "#6b2f2f;background:#1c0f0f;color:#f0b0b0");
      flag.textContent = n
        ? "\u2713 " + (d.caller_name || "the caller") + " has " + n
          + " turn(s) in this call."
        : "\u26a0 Nobody is on the phone in this call \u2014 every line "
          + "is a host. It will air as two presenters talking about a "
          + "caller who never speaks.";
      drw.appendChild(flag);
    }
    lines.forEach((ln) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;gap:4px;align-items:flex-start;"
        + "font-size:9.5px;padding:2px 0;border-bottom:"
        + "1px solid rgba(255,255,255,.05)";
      const who = document.createElement("span");
      who.textContent = ln.name || ln.who || "";
      who.style.cssText = "min-width:46px;color:#9fd8ff;flex:none";
      row.appendChild(who);
      const txt = document.createElement("span");
      txt.textContent = ln.text || "";
      txt.style.cssText = "flex:1;min-width:0;line-height:1.45;"
        + "white-space:pre-wrap";
      row.appendChild(txt);
      const meta = document.createElement("span");
      meta.className = "wk-note";
      meta.style.cssText = "font-size:9px;opacity:.6;flex:none";
      /* #959: a caller's turn is not a missing take — it is a turn whose
       * phone line is drawn at the moment the call airs, so "not cut" was
       * the wrong word for the one row that most needed the right one. */
      meta.textContent = ln.live ? "voiced on the call"
        : ln.recorded ? Math.round(ln.seconds) + "s" : "not cut";
      if (ln.live) who.style.color = "#ffd7a1";
      row.appendChild(meta);
      if (ln.recorded) {
        const play = document.createElement("button");
        play.textContent = "\u25b6";
        play.title = "Play this line";
        play.style.cssText = "font-size:8px;padding:0 4px;flex:none";
        play.onclick = (e2) => {
          e2.stopPropagation();
          const old = row.querySelector("audio");
          if (old) { old.remove(); return; }
          const au = document.createElement("audio");
          au.controls = true;
          au.autoplay = true;
          au.src = wkMediaUrl(ln);
          au.style.cssText = "width:100%;height:24px;margin-top:2px";
          row.appendChild(au);
        };
        row.appendChild(play);
        const keep = document.createElement("button");
        keep.textContent = "\u2b07";
        keep.title = "Keep this line";
        keep.style.cssText = "font-size:8px;padding:0 4px;flex:none";
        keep.onclick = (e2) => {
          e2.stopPropagation();
          /* #898: this line's OWN clip, saved. */
          wkSaveBlob(wkMediaUrl(ln),
                     wkFileName((ln.name || ln.who || "line") + " "
                                + (ln.text || ""), "wav"), keep);
        };
        row.appendChild(keep);
      }
      drw.appendChild(row);
    });
  };

  host.appendChild(bar);
  host.appendChild(player);
  host.appendChild(drw);
}

/* #902: THE REVIEW - one prepared section, opened right out.
 *
 * "show me the transcript, the recording offering me to download it...
 *  If I click on a phrase of the transcript, I want to play that out
 *  loud... expand each and every line of the transcript and be able to
 *  see how the scripting was done for it... and be able to even modify
 *  what's going on here and resubmit it... stacking another version in
 *  the pantry that is stacked higher."
 *
 * Almost all of this already existed and was simply scattered:
 * /api/shelf/candidate is the transcript with a signed, playable media
 * key on every line (#935), /api/shelf/bundle is the welded whole
 * (#935), and the round's own writing paperwork rides on the section as
 * `stats` (#941). This puts them on one page and adds the one thing
 * that was missing - an edit box that goes back through the rooms
 * (POST /api/shelf/recast) and lands ABOVE the round it came from. */
let wkReviewAudio = null;

function wkReviewClose() {
  try { if (wkReviewAudio) wkReviewAudio.pause(); } catch (e) { /* fine */ }
  wkReviewAudio = null;
  const gone = document.getElementById("wkReview");
  if (gone) gone.remove();
}

function wkReviewRow(host, label, value) {
  if (value === "" || value === null || value === undefined) return null;
  const r = document.createElement("div");
  r.style.cssText = "display:flex;gap:8px;padding:2px 0;font-size:9.5px;"
    + "border-top:1px solid rgba(255,255,255,.06)";
  const k = document.createElement("div");
  k.textContent = String(label);
  k.style.cssText = "flex:0 0 112px;opacity:.6;word-break:break-word";
  const v = document.createElement("div");
  v.textContent = String(value);
  v.style.cssText = "flex:1;min-width:0;word-break:break-word";
  r.appendChild(k);
  r.appendChild(v);
  host.appendChild(r);
  return r;
}

function wkReviewHead(host, text) {
  const h = document.createElement("div");
  h.textContent = text;
  h.style.cssText = "font-size:9px;letter-spacing:.06em;font-weight:700;"
    + "color:#9fd8ff;margin:11px 0 3px;opacity:.85";
  host.appendChild(h);
  return h;
}

function wkReviewBtn(host, text, title) {
  const b = document.createElement("button");
  b.textContent = text;
  b.title = title || "";
  b.style.cssText = "font-size:9.5px;padding:2px 8px";
  host.appendChild(b);
  return b;
}

function wkReviewPopup(kind, id) {
  wkReviewClose();
  const pop = document.createElement("div");
  pop.id = "wkReview";
  pop.style.cssText = "position:fixed;left:50%;top:4vh;"
    + "transform:translateX(-50%);z-index:520;width:min(700px,95vw);"
    + "max-height:90vh;overflow:auto;padding:12px 14px;border-radius:9px;"
    + "background:#080d14;border:1px solid #24384a;color:#cfe3f4;"
    + "box-shadow:0 18px 54px rgba(0,0,0,.82);font-size:10.5px;"
    + "line-height:1.5";
  pop.onclick = (ev) => ev.stopPropagation();

  const head = document.createElement("div");
  head.style.cssText = "display:flex;gap:8px;align-items:baseline";
  const ttl = document.createElement("b");
  ttl.textContent = "\u25a4 reading the tape\u2026";
  ttl.style.cssText = "flex:1;font-size:12px;color:#9fd8ff";
  const shut = document.createElement("span");
  shut.textContent = "\u2715";
  shut.style.cssText = "cursor:pointer;opacity:.6";
  shut.onclick = wkReviewClose;
  head.appendChild(ttl);
  head.appendChild(shut);
  pop.appendChild(head);

  const body = document.createElement("div");
  body.textContent = "reading the tape\u2026";
  pop.appendChild(body);
  document.body.appendChild(pop);

  const esc = (ev) => {
    if (ev.key !== "Escape") return;
    document.removeEventListener("keydown", esc);
    wkReviewClose();
  };
  document.addEventListener("keydown", esc);

  /* The script box is made up front: a per-line edit patches ITS text,
   * so the one thing that goes back to the rooms is the one thing the
   * operator can see in full. */
  const scriptBox = document.createElement("textarea");

  api.get("/api/shelf/candidate?kind=" + encodeURIComponent(kind)
          + "&id=" + encodeURIComponent(id))
    .then((d) => {
      try { fill(d); }
      catch (e) {
        body.textContent = "that section could not be drawn: "
          + (e && e.message ? e.message : "unknown");
      }
    })
    .catch((e) => {
      body.textContent = "that section could not be read: "
        + (e && e.message ? e.message : "no answer");
    });

  function fill(d) {
    body.textContent = "";
    const lines = d.lines || [];
    ttl.textContent = "\u25a4 " + (d.label || kind) + " \u00b7 "
      + lines.length + " line(s)";

    const facts = document.createElement("div");
    wkReviewRow(facts, "on the shelf", (d.kind || kind) + " \u00b7 "
                + (d.id || id));
    wkReviewRow(facts, "written", Math.round(d.age_minutes || 0)
                + " min ago");
    wkReviewRow(facts, "recorded", Math.round(d.seconds || 0)
                + "s of finished audio \u00b7 "
                + lines.filter((l) => l.recorded).length + " of "
                + lines.length + " lines cut");
    wkReviewRow(facts, "stacked",
                ((d.priority || 0) > 0 ? "+" : "") + (d.priority || 0)
                + ((d.priority || 0) ? " \u2014 above the untouched ones"
                                     : " \u2014 untouched"));
    if (d.recast_from) {
      wkReviewRow(facts, "your recast of", d.recast_from);
    }
    if (d.note) wkReviewRow(facts, "your note", d.note);
    if (d.derived) {
      wkReviewRow(facts, "note", "prepared before the takes were written "
        + "down \u2014 these lines are rederived exactly as the air road "
        + "derives them");
    }
    body.appendChild(facts);

    /* --- the recording ------------------------------------------- */
    wkReviewHead(body, "THE RECORDING");
    const tape = document.createElement("div");
    tape.style.cssText = "display:flex;gap:5px;align-items:center;"
      + "flex-wrap:wrap";
    const player = document.createElement("div");
    player.style.marginTop = "4px";
    let welded = null;
    const weld = async (btn) => {
      if (welded) return welded;
      const was = btn.textContent;
      btn.disabled = true;
      btn.textContent = "welding\u2026";
      try {
        welded = await api.get("/api/shelf/bundle?kind="
                               + encodeURIComponent(kind) + "&id="
                               + encodeURIComponent(id));
      } finally {
        btn.textContent = was;
        btn.disabled = false;
      }
      return welded;
    };
    wkReviewBtn(tape, "\u25b6 play the whole thing",
                "Weld this section end to end the way it would go out, "
                + "and play it").onclick = async (ev) => {
      try {
        const got = await weld(ev.target);
        player.textContent = "";
        const au = document.createElement("audio");
        au.controls = true;
        au.autoplay = true;
        au.src = wkMediaUrl(got);
        au.style.cssText = "width:100%;height:28px";
        player.appendChild(au);
        wkReviewAudio = au;
        const note2 = document.createElement("div");
        note2.style.cssText = "font-size:9px;opacity:.6";
        note2.textContent = got.lines + " lines \u00b7 "
          + Math.round(got.seconds) + "s \u00b7 "
          + Math.round((got.bytes || 0) / 1024) + " KB";
        player.appendChild(note2);
      } catch (e) {
        player.textContent = /409/.test(String(e && e.message))
          ? "nothing in this section has been recorded yet \u2014 there "
            + "is a script but no audio to weld"
          : "it could not be welded";
      }
    };
    wkReviewBtn(tape, "\u2b07 download it",
                "Save the whole section as one file").onclick =
        async (ev) => {
      const btn = ev.target;
      try {
        const got = await weld(btn);
        await wkSaveBlob(wkMediaUrl(got),
                         wkFileName((d.label || kind) + " " + id, "wav"),
                         btn);
      } catch (e) { btn.textContent = "could not weld"; }
    };
    body.appendChild(tape);
    body.appendChild(player);

    /* --- the transcript ------------------------------------------ */
    wkReviewHead(body, "THE TRANSCRIPT \u2014 CLICK ANY PHRASE TO HEAR IT");
    if (!lines.length) {
      const none = document.createElement("div");
      none.style.cssText = "font-size:9.5px;opacity:.6";
      none.textContent = d.why || "nothing was written down for this one";
      body.appendChild(none);
    }
    lines.forEach((ln, ix) => {
      const box = document.createElement("div");
      box.style.cssText = "padding:3px 0;border-bottom:"
        + "1px solid rgba(255,255,255,.05)";
      const top = document.createElement("div");
      top.style.cssText = "display:flex;gap:5px;align-items:flex-start";
      const tri = document.createElement("button");
      tri.textContent = "\u25b8";
      tri.title = "How this line was made";
      tri.style.cssText = "font-size:9px;padding:0 4px;flex:none";
      top.appendChild(tri);
      const who = document.createElement("span");
      who.textContent = ln.name || ln.who || "";
      who.style.cssText = "flex:none;min-width:52px;color:#9fd8ff;"
        + "font-size:9.5px";
      top.appendChild(who);
      const txt = document.createElement("span");
      txt.textContent = ln.text || "";
      txt.style.cssText = "flex:1;min-width:0;white-space:pre-wrap;"
        + "line-height:1.5"
        + (ln.recorded ? ";cursor:pointer" : ";opacity:.6");
      txt.title = ln.recorded
        ? "Click to hear this phrase on its own"
        : "not cut yet \u2014 this one renders on air";
      if (ln.recorded) {
        txt.onclick = (e2) => {
          e2.stopPropagation();
          const old = box.querySelector("audio");
          if (old) { old.remove(); return; }
          const au = document.createElement("audio");
          au.controls = true;
          au.autoplay = true;
          au.src = wkMediaUrl(ln);
          au.style.cssText = "width:100%;height:24px;margin-top:2px";
          box.appendChild(au);
          wkReviewAudio = au;
        };
      }
      top.appendChild(txt);
      const meta = document.createElement("span");
      meta.textContent = ln.recorded ? Math.round(ln.seconds) + "s"
                                     : "not cut";
      meta.style.cssText = "flex:none;font-size:9px;opacity:.55";
      top.appendChild(meta);
      if (ln.recorded) {
        const keep = document.createElement("button");
        keep.textContent = "\u2b07";
        keep.title = "Download just this phrase";
        keep.style.cssText = "font-size:9px;padding:0 4px;flex:none";
        keep.onclick = (e2) => {
          e2.stopPropagation();
          wkSaveBlob(wkMediaUrl(ln),
                     wkFileName((ln.name || ln.who || "line") + " "
                                + (ln.text || ""), "wav"), keep);
        };
        top.appendChild(keep);
      }
      box.appendChild(top);

      const inner = document.createElement("div");
      inner.style.cssText = "display:none;margin:3px 0 5px 22px";
      tri.onclick = (e2) => {
        e2.stopPropagation();
        const on = inner.style.display === "none";
        inner.style.display = on ? "block" : "none";
        tri.textContent = on ? "\u25be" : "\u25b8";
        if (!on || inner.childNodes.length) return;
        wkReviewRow(inner, "seat", ln.who || "\u2014");
        wkReviewRow(inner, "voice", ln.voice || "\u2014");
        wkReviewRow(inner, "engine", ln.engine || "\u2014");
        wkReviewRow(inner, "in the script",
                    "line " + ((ln.i == null ? ix : ln.i) + 1));
        wkReviewRow(inner, "pantry key", ln.key || "\u2014");
        wkReviewRow(inner, "recorded", ln.recorded
          ? Math.round(ln.seconds) + "s standing on the shelf"
          : "not yet \u2014 it renders the moment it airs");
        /* The transcript is what was SAID; the script is what was
         * WRITTEN, and the recording room breaks a long turn into
         * pieces and puts the breaths and stumbles in on the way past.
         * When the phrase is in the script verbatim, editing it here
         * patches the script below. When it is not, say so rather than
         * pretending the edit will land. */
        const at0 = String(scriptBox.value).indexOf(String(ln.text || ""));
        if (!ln.text || at0 < 0) {
          const warn = document.createElement("div");
          warn.style.cssText = "font-size:9px;margin-top:3px;"
            + "color:#e0a35c;line-height:1.5";
          warn.textContent = "this phrase is not in the script word for "
            + "word \u2014 the recording room cut the turn into pieces "
            + "and put the breaths in on the way past, so edit the "
            + "script itself further down";
          inner.appendChild(warn);
          return;
        }
        let cur = String(ln.text || "");
        const ed = document.createElement("textarea");
        ed.value = cur;
        ed.spellcheck = false;
        ed.title = "Change what this line says. It patches the script "
          + "below; nothing moves until you send the section back.";
        ed.style.cssText = "width:100%;min-height:46px;margin-top:4px;"
          + "font-size:10px;line-height:1.5;background:#05090f;"
          + "color:#cfe3f4;border:1px solid #24384a;border-radius:5px;"
          + "padding:4px 6px";
        ed.oninput = () => {
          const at1 = scriptBox.value.indexOf(cur);
          if (at1 < 0) return;
          scriptBox.value = scriptBox.value.slice(0, at1) + ed.value
            + scriptBox.value.slice(at1 + cur.length);
          cur = ed.value;
          txt.textContent = ed.value;
        };
        inner.appendChild(ed);
      };
      box.appendChild(inner);
      body.appendChild(box);
    });

    /* --- how it was written -------------------------------------- */
    const st = d.stats || {};
    const known = ["temp", "heat", "turns", "chunks", "made", "seconds"];
    if (Object.keys(st).length) {
      wkReviewHead(body, "HOW IT WAS WRITTEN");
      const paper = document.createElement("div");
      wkReviewRow(paper, "temperature",
                  st.temp === undefined ? "\u2014" : st.temp);
      wkReviewRow(paper, "heat dial",
                  st.heat === undefined ? "\u2014" : st.heat);
      wkReviewRow(paper, "turns written",
                  st.turns === undefined ? "\u2014" : st.turns);
      wkReviewRow(paper, "lines cut",
                  (st.made === undefined ? "?" : st.made) + " of "
                  + (st.chunks === undefined ? "?" : st.chunks));
      Object.keys(st).forEach((k) => {
        if (known.indexOf(k) >= 0) return;
        const v = st[k];
        wkReviewRow(paper, k, (v && typeof v === "object")
          ? JSON.stringify(v).slice(0, 220) : v);
      });
      body.appendChild(paper);
    }

    /* --- the script, and sending it back ------------------------- */
    wkReviewHead(body,
                 "THE SCRIPT AS WRITTEN \u2014 CHANGE IT AND SEND IT BACK");
    scriptBox.value = String(d.script || "");
    scriptBox.spellcheck = false;
    scriptBox.title = "A: is the host, B: the co-host, C: the caller, "
      + "D: the third seat, E: a second caller.";
    scriptBox.style.cssText = "width:100%;min-height:170px;font-size:10px;"
      + "line-height:1.55;background:#05090f;color:#cfe3f4;"
      + "border:1px solid #24384a;border-radius:6px;padding:6px 8px;"
      + "font-family:ui-monospace,Consolas,monospace";
    body.appendChild(scriptBox);

    const note = document.createElement("input");
    note.placeholder = "why (kept on the round, and read by the desk if "
      + "you ask for a rewrite)";
    note.style.cssText = "width:100%;margin-top:4px;font-size:9.5px;"
      + "padding:3px 6px;background:#05090f;color:#cfe3f4;"
      + "border:1px solid #24384a;border-radius:5px";
    body.appendChild(note);

    const opts = document.createElement("label");
    opts.style.cssText = "display:flex;gap:5px;align-items:flex-start;"
      + "margin-top:5px;font-size:9.5px;opacity:.82;line-height:1.45";
    const rw = document.createElement("input");
    rw.type = "checkbox";
    rw.style.cssText = "flex:none;margin-top:2px";
    opts.appendChild(rw);
    opts.appendChild(document.createTextNode(
      "let the writing room have a pass over my version first \u2014 "
      + "off means my words are recorded exactly as typed"));
    body.appendChild(opts);

    const send = document.createElement("button");
    send.textContent = "\u270e record my version and stack it on top";
    send.title = "Through the recording room, onto the shelf ABOVE the "
      + "one it came from \u2014 so it is the one that goes out next.";
    send.style.cssText = "margin-top:7px;font-size:10px;padding:4px 11px";
    const watch = document.createElement("div");
    watch.style.cssText = "font-size:9.5px;opacity:.78;margin-top:5px;"
      + "line-height:1.5";
    send.onclick = async () => {
      send.disabled = true;
      watch.textContent = "asking the desk\u2026";
      let job = null;
      try {
        job = await api.post("/api/shelf/recast", {
          id: id,
          script: scriptBox.value,
          note: note.value,
          rewrite: rw.checked,
          promote: true,
        });
      } catch (e) {
        watch.textContent = "the desk refused that: "
          + (e && e.message ? e.message : "no answer");
        send.disabled = false;
        return;
      }
      watch.textContent = "queued \u2014 it takes the spare engine slot "
        + "in a quiet stretch, so the live round never waits on it";
      const done = ["done", "refused", "failed", "gave up"];
      const tick = async () => {
        let s = null;
        try {
          s = await api.get("/api/schedule/segment/generate/"
                            + encodeURIComponent(job.job));
        } catch (e) {
          watch.textContent = "the ticket could not be read";
          send.disabled = false;
          return;
        }
        watch.textContent = String(s.state || "?")
          + (s.why ? " \u2014 " + s.why : "")
          + (s.made ? " \u00b7 " + s.made + " stacked" : "");
        if (done.indexOf(String(s.state)) < 0) {
          setTimeout(tick, 2500);
          return;
        }
        send.disabled = false;
        if (String(s.state) === "done") {
          watch.textContent = "recorded and stacked on top \u2014 it is "
            + "the one that goes out next";
        }
      };
      setTimeout(tick, 1500);
    };
    body.appendChild(send);
    body.appendChild(watch);
  }
}

/* The Works' own popups are plain divs, not the panel's — give them the
 * same "stay on screen" courtesy (#877). */
/* #914: move a popup by any BLANK part of itself.
 *
 * Only blank parts: a drag beginning on a button, an input, a select, a
 * link or an audio player would steal the click from the control you
 * were aiming at, and these windows are almost entirely controls. A
 * drag that begins inside live selected text is left alone too — #883
 * exists precisely because this window kept interrupting people who
 * were reading it. */
function wkDraggable(el2) {
  try {
    if (!el2 || el2.dataset.wkDrag) return;
    el2.dataset.wkDrag = "1";
    const CONTROLS = "button, input, select, textarea, a, audio, option, "
      + "label, [contenteditable]";
    let from = null;
    el2.addEventListener("mousedown", (ev) => {
      if (ev.button !== 0) return;
      const t = ev.target;
      if (t && t.closest && t.closest(CONTROLS)) return;
      try {
        const sel = window.getSelection();
        if (sel && !sel.isCollapsed) return;   // they are selecting
      } catch (e) { /* drag anyway */ }
      const r = el2.getBoundingClientRect();
      from = {x: ev.clientX, y: ev.clientY, left: r.left, top: r.top};
      el2.style.position = "fixed";
      el2.style.left = Math.round(r.left) + "px";
      el2.style.top = Math.round(r.top) + "px";
      el2.style.right = "auto";
      el2.style.bottom = "auto";
      ev.preventDefault();
    });
    const move = (ev) => {
      if (!from) return;
      el2.style.left = Math.round(from.left + ev.clientX - from.x) + "px";
      el2.style.top = Math.round(from.top + ev.clientY - from.y) + "px";
    };
    const drop = () => {
      if (!from) return;
      from = null;
      try { pvFloatDesk(el2); } catch (e) { /* it is where it is */ }
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", drop);
    el2.style.cursor = el2.style.cursor || "default";
  } catch (e) { /* the window still opens */ }
}

function pvFloatDesk(el2) {
  try {
    const r = el2.getBoundingClientRect();
    const mw = window.innerWidth, mh = window.innerHeight;
    el2.style.left = Math.round(Math.min(Math.max(8, r.left),
                                         Math.max(8, mw - r.width - 8))) + "px";
    el2.style.top = Math.round(Math.min(Math.max(8, r.top),
                                        Math.max(8, mh - r.height - 8))) + "px";
  } catch (e) {}
}

/* #799: the status bar — the machine's own ticker tape. Left: the newest
 * line of EVERYTHING the server is doing (pipeline feed + every shell
 * command the agent runs), click for the live 8-line terminal with
 * click-to-expand detail. Right: the go-live switch and a marquee of the
 * Spark's vitals and heaviest tenants. */
/* #859: CALL THE BOOTH. Hold the ☎, talk, let go and you are on air.
 * The station already has the road — POST raw 16-bit mono PCM to
 * /api/dj/callin/voice and it transcribes, spots a song request, or
 * hands the pair a topic to take on air. All this end has to do is
 * capture the mic honestly and resample to what the recogniser wants. */
const CALLIN_RATE = 16000;
let callInState = null;

function callInSay(text, bad) {
  const note = $("callInNote");
  if (note) {
    note.textContent = text;
    note.style.color = bad ? "#ff9db1" : "#7ce8a9";
  }
  try { setStatus(text, !!bad); } catch (e) { /* rail-only */ }
}

function callInPanel() {
  let box = $("callInPanel");
  if (box) return box;
  box = document.createElement("div");
  box.id = "callInPanel";
  box.style.cssText = "position:fixed;left:52px;bottom:64px;z-index:120;"
    + "width:min(340px,86vw);background:var(--panel,#141b24);"
    + "border:1px solid #2a5c3f;border-radius:10px;padding:12px;"
    + "box-shadow:0 14px 44px rgba(0,20,8,.8);font-size:12.5px;"
    + "display:flex;flex-direction:column;gap:8px";
  box.innerHTML = "<b>\u260e Call the booth</b>"
    + "<div class='muted' style='font-size:11px'>Hold the button, say "
    + "your piece, let go. You can raise a topic or just ask for a "
    + "song \u2014 they take both.</div>"
    + "<button id='callInHold' style='padding:10px;font-weight:700'>"
    + "\ud83c\udf99 Hold to talk</button>"
    + "<div id='callInNote' class='muted' style='font-size:11px'></div>"
    + "<div id='callInHeard' style='font-size:11.5px;line-height:1.5'></div>";
  const shut = document.createElement("button");
  shut.textContent = "\u2715";
  shut.style.cssText = "position:absolute;top:8px;right:10px";
  shut.onclick = () => { callInStop(true); box.remove(); };
  box.appendChild(shut);
  document.body.appendChild(box);

  const hold = box.querySelector("#callInHold");
  hold.onmousedown = callInStart;
  hold.onmouseup = () => callInStop(false);
  hold.onmouseleave = () => { if (callInState) callInStop(false); };
  hold.ontouchstart = (ev) => { ev.preventDefault(); callInStart(); };
  hold.ontouchend = (ev) => { ev.preventDefault(); callInStop(false); };
  return box;
}

async function callInStart() {
  if (callInState) return;
  const hold = $("callInHold");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {channelCount: 1, echoCancellation: true,
              noiseSuppression: true}});
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const source = ctx.createMediaStreamSource(stream);
    // ScriptProcessor is deprecated but it is the one node available in
    // every Electron build without shipping a worklet file alongside.
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    node.onaudioprocess = (ev) => {
      chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    source.connect(node);
    node.connect(ctx.destination);
    callInState = {stream, ctx, source, node, chunks};
    if (hold) { hold.textContent = "\u25cf recording\u2026 let go to send"; }
    callInSay("listening \u2014 the booth is waiting");
  } catch (err) {
    callInSay("no microphone: " + err.message, true);
  }
}

function callInFloatsTo16k(chunks, fromRate) {
  let total = 0;
  chunks.forEach((c) => { total += c.length; });
  const flat = new Float32Array(total);
  let at = 0;
  chunks.forEach((c) => { flat.set(c, at); at += c.length; });
  // Linear resample to what the recogniser wants, then 16-bit signed.
  const ratio = fromRate / CALLIN_RATE;
  const out = new Int16Array(Math.floor(flat.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const src = i * ratio;
    const lo = Math.floor(src);
    const hi = Math.min(flat.length - 1, lo + 1);
    const v = flat[lo] + (flat[hi] - flat[lo]) * (src - lo);
    out[i] = Math.max(-1, Math.min(1, v)) * 0x7fff;
  }
  return out;
}

async function callInStop(silent) {
  const state = callInState;
  callInState = null;
  const hold = $("callInHold");
  if (hold) hold.textContent = "\ud83c\udf99 Hold to talk";
  if (!state) return;
  try {
    state.node.disconnect();
    state.source.disconnect();
    state.stream.getTracks().forEach((t) => t.stop());
  } catch (e) { /* already torn down */ }
  const rate = state.ctx.sampleRate || 48000;
  try { await state.ctx.close(); } catch (e) { /* fine */ }
  if (silent) return;
  const pcm = callInFloatsTo16k(state.chunks, rate);
  if (pcm.length < 1600) {          // under a tenth of a second
    callInSay("that was too short \u2014 hold it a moment longer", true);
    return;
  }
  callInSay("on the line\u2026 they are listening back");
  try {
    const cfg = await api.readConfig();
    const reply = await fetch(
      `${cfg.baseUrl}/api/dj/callin/voice?rate=${CALLIN_RATE}`,
      {method: "POST",
       headers: {"Authorization": "Bearer " + (cfg.apiKey || ""),
                 "Content-Type": "application/octet-stream"},
       body: pcm.buffer});
    const got = await reply.json().catch(() => ({}));
    if (!reply.ok) throw new Error(got.detail || ("HTTP " + reply.status));
    const heard = $("callInHeard");
    if (got.heard) {
      callInSay(got.kind === "request"
        ? "they took your request" : "you are on air");
      if (heard) {
        heard.innerHTML = "<div style='color:#9fd8ff'>you said: "
          + String(got.heard).replace(/[&<>]/g, "") + "</div>"
          + (got.lines || []).map((l) =>
              "<div style='margin-top:4px'>\u2014 "
              + String(l).replace(/[&<>]/g, "") + "</div>").join("");
      }
    } else {
      callInSay(got.detail || "nothing came through \u2014 try again",
                true);
    }
  } catch (err) {
    callInSay("the booth did not pick up: " + err.message, true);
  }
}

function initCallIn() {
  const btn = $("callInBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const box = $("callInPanel");
    if (box) { callInStop(true); box.remove(); return; }
    callInPanel();
  });
}
initCallIn();

function initStatusBar() {
  const line = $("sbTermLine");
  const pop = $("sbTermPopup");
  const marq = $("sbMarqueeInner");
  const liveBtn = $("sbLiveBtn");
  if (!line || !pop) return;

  const ring = [];              // {ts, kind, text, extra} — newest last
  const feedSeen = new Set();   // #801: dedupe across the merged feeds
  let lastPipe = 0, lastShell = 0, counts = {}, open = false;

  const esc = (s) => String(s).replace(/[&<>]/g, (c) =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
  const when = (ts) => new Date(ts).toLocaleTimeString();

  function push(e) {
    ring.push(e);
    if (ring.length > 500) ring.splice(0, ring.length - 500);
    counts[e.kind] = (counts[e.kind] || 0) + 1;
  }

  async function pollFeed() {
    try {
      const p = await api.get("/api/dj/pipeline?since=" + lastPipe);
      (p.events || []).forEach((e) => {
        lastPipe = Math.max(lastPipe, e.ts || 0);
        push({ts: e.ts, kind: e.kind || "…", text: e.text || "",
              extra: e.extra || ""});
      });
    } catch { /* agent quiet — the bar keeps its last words */ }
    try {
      const perf = await api.get("/api/perf");
      (perf.shell || []).slice().reverse().forEach((s) => {
        if ((s.ts || 0) <= lastShell) return;
        lastShell = Math.max(lastShell, s.ts || 0);
        push({ts: s.ts, kind: "shell",
              text: "$ " + (s.cmd || "") + (s.rc != null
                ? " → rc " + s.rc + (s.ms != null ? " · " + s.ms + "ms" : "")
                : " (running)"),
              extra: ""});
      });
    } catch { /* same */ }
    // #801: the WHOLE station, not just the glass — booth lines as they
    // air, the repair ledger, the activity trail. Deduped by signature so
    // the merged feeds never double-report one event.
    try {
      const r = await api.get("/api/radio");
      const seenAdd = (ts, kind, text, extra) => {
        const key = kind + "|" + ts + "|" + (text || "").slice(0, 60);
        if (feedSeen.has(key)) return;
        feedSeen.add(key);
        if (feedSeen.size > 1200) {
          feedSeen.clear();               // cheap reset; dupes age out
        }
        push({ts, kind, text, extra: extra || ""});
      };
      (r.chat || []).slice(-15).forEach((c) => {
        // #803: the line's WHOLE LIFE rides in the expandable detail —
        // who wrote it, what fed it (speakbox seed, system prompt), what
        // modified it, what voiced it. Every field the server tracks on
        // the row (#782), minus the text itself.
        const prov = {};
        Object.keys(c).forEach((k) => {
          if (k !== "text" && c[k] != null && c[k] !== "") prov[k] = c[k];
        });
        seenAdd((c.ts || 0) * 1000, c.kind === "hangup" ? "call" : "booth",
          (c.who || "") + ": " + (c.text || ""),
          "— provenance —\n" + JSON.stringify(prov, null, 1).slice(0, 1800));
      });
      (r.repair_log || []).slice(-8).forEach((c) => {
        seenAdd((c.at || 0) * 1000, "repair", c.what || "", "");
      });
      (r.activity_log || []).slice(-12).forEach((c) => {
        seenAdd((c.at || 0) * 1000, "activity",
          (c.stage || "") + (c.detail ? " · " + c.detail : ""), "");
      });
    } catch { /* the bar keeps what it has */ }
    const last = ring[ring.length - 1];
    if (last) {
      line.textContent = when(last.ts) + "  [" + last.kind + "]  " + last.text;
    }
    // #826: while the reader is scrolled up, the popup is FROZEN — no
    // redraw, no motion of any kind. New entries wait in the ring and a
    // pill counts them; scrolling back to the bottom resumes the flow.
    if (open && stickBottom && !reading) {
      frozenAt = ring.length;
      drawPop();
    } else if (open) {
      const pill = pop.querySelector(".sb-pill");
      const fresh = ring.length - frozenAt;
      if (pill) {
        pill.textContent = fresh > 0
          ? "\u2193 " + fresh + " new below \u2014 scroll to bottom to resume"
          : "paused \u2014 reading";
        pill.style.display = "block";
      }
    }
    setTimeout(pollFeed, 2500);
  }

  // #801: the terminal grown up — tabs, ×N grouping of duplicates,
  // 300-deep scrollback, right-click → "other", resizable + remembered,
  // and a 🗑 on any row naming a voice to mark it for deletion review.
  // #802: tabs matched to the pipeline's REAL kinds. Talk carries the
  // whole conversation machine — the model calls WITH their prompts (the
  // expandable detail is the actual system prompt and the actual reply),
  // the rounds, the air. Speakbox is everything vector: mining, seeds,
  // themes, who called it and what received the assignment — plus the
  // full database on demand. Voice is every render, refinement and
  // engine event.
  const TABS = {All: null,
    Voice: ["voice", "voicing", "gpu", "render", "synth", "perf"],
    Talk: ["call", "air", "banter", "booth", "model", "plan", "write",
           "lookahead", "action", "drop"],
    Speakbox: ["speakbox", "theme", "mine", "seed", "embed"],
    Station: ["repair", "activity"],
    Shell: ["shell"], Other: "other"};
  let tab = localStorage.getItem("sbTermTab") || "All";
  const otherTags = new Set(JSON.parse(
    localStorage.getItem("sbOtherTags") || "[]"));
  const sig = (e) => (e.kind || "") + "|" + (e.text || "").slice(0, 80);
  let scroller = null, stickBottom = true, frozenAt = 0, reading = false;

  function drawPop() {
    const openedKeys = new Set(Array.from(
      pop.querySelectorAll(".sb-row.open")).map((r) => r.dataset.key));
    pop.innerHTML = "";
    const tabs = document.createElement("div");
    tabs.className = "sb-tabs";
    Object.keys(TABS).forEach((name) => {
      const b = document.createElement("button");
      b.textContent = name;
      b.className = name === tab ? "on" : "";
      b.onclick = (ev) => { ev.stopPropagation(); tab = name;
        localStorage.setItem("sbTermTab", name); drawPop(); };
      tabs.appendChild(b);
    });
    // #802: the Speakbox tab can open the whole vector database.
    if (tab === "Speakbox") {
      const db = document.createElement("button");
      db.textContent = "📚 full database";
      db.onclick = async (ev) => {
        ev.stopPropagation();
        try {
          const got = await api.get("/api/speakbox");
          const rows = (got.docs || got.entries || got.list
            || got.swaths || []);
          push({ts: Date.now(), kind: "speakbox",
            text: "— the database: " + rows.length + " entrie(s) —",
            extra: JSON.stringify(got, null, 1).slice(0, 1900)});
          drawPop();
        } catch (err) {
          push({ts: Date.now(), kind: "speakbox", text: err.message,
                extra: ""});
          drawPop();
        }
      };
      tabs.appendChild(db);
    }
    // #804: size to the number of entries you want to READ. Presets set
    // the height to fit that many rows exactly; the grip and edges still
    // drag anywhere in between, and every size is remembered.
    const sizer = document.createElement("span");
    sizer.style.cssText = "margin-left:auto;display:flex;gap:3px";
    [["8", 8], ["20", 20], ["40", 40], ["Max", 0]].forEach(([lbl, rows]) => {
      const b = document.createElement("button");
      b.textContent = lbl;
      b.title = rows ? "show ~" + rows + " entries" : "fill the window";
      b.onclick = (ev) => {
        ev.stopPropagation();
        if (rows) {
          pop.style.height = (rows * 18 + 72) + "px";
        } else {
          pop.style.height = "94vh";
          pop.style.width = "98vw";
        }
        localStorage.setItem("sbTermSize", JSON.stringify(
          {w: pop.offsetWidth, h: pop.offsetHeight}));
        drawPop();
      };
      sizer.appendChild(b);
    });
    tabs.appendChild(sizer);
    pop.appendChild(tabs);
    // #802: rebuilding the list must never yank the view — remember where
    // the reader was and put them back there unless they were riding the
    // tail on purpose.
    const oldTop = scroller ? scroller.scrollTop : 0;
    scroller = document.createElement("div");
    scroller.className = "sb-scroll";
    scroller.addEventListener("scroll", () => {
      const was = stickBottom;
      stickBottom = scroller.scrollTop + scroller.clientHeight
        >= scroller.scrollHeight - 20;
      // #826: returning to the tail thaws the frozen view at once.
      if (stickBottom && !was) {
        const pill = pop.querySelector(".sb-pill");
        if (pill) pill.style.display = "none";
        frozenAt = ring.length;
        drawPop();
      }
      if (!stickBottom) {
        const pill = pop.querySelector(".sb-pill");
        if (pill) pill.style.display = "block";
      }
    });
    pop.appendChild(scroller);
    if (!pop.querySelector(".sb-pill")) {
      const pill = document.createElement("div");
      pill.className = "sb-pill";
      pill.style.cssText = "position:absolute;left:50%;bottom:8px;" +
        "transform:translateX(-50%);z-index:3;display:none;" +
        "background:#17475a;color:#c8f5da;border:1px solid #65c7da;" +
        "border-radius:99px;padding:2px 12px;font-size:10.5px;" +
        "cursor:pointer;white-space:nowrap";
      pill.onclick = () => {
        stickBottom = true;
        pill.style.display = "none";
        frozenAt = ring.length;
        drawPop();
      };
      pop.appendChild(pill);
    }

    const want = TABS[tab];
    const shown = ring.filter((e) => {
      const tagged = otherTags.has(sig(e));
      if (want === "other") return tagged;
      if (tagged) return false;
      return !want || want.includes(e.kind);
    }).slice(-300);
    // Consecutive duplicates fold into one row with a live ×N.
    const grouped = [];
    shown.forEach((e) => {
      const last = grouped[grouped.length - 1];
      if (last && sig(last.e) === sig(e)) { last.n += 1; last.e = e; }
      else grouped.push({e, n: 1});
    });
    grouped.forEach(({e, n}) => {
      const row = document.createElement("div");
      row.className = "sb-row sb-kind-" + (e.kind || "x");
      row.dataset.key = sig(e) + e.ts;
      const vid = ((e.text || "") + " " + (e.extra || ""))
        .match(/vl_[0-9a-f]{6,}/);
      row.innerHTML = "<span class='sb-when'>" + when(e.ts) + "</span> "
        + "<span class='sb-kind'>[" + esc(e.kind) + "]</span> "
        + esc(e.text)
        + (n > 1 ? " <span class='sb-count'>(×" + n + ")</span>" : "")
        + (e.extra ? "\n——— detail ———\n" + esc(e.extra) : "");
      if (openedKeys.has(row.dataset.key)) row.classList.add("open");
      row.title = (e.extra ? "click for the full detail · " : "")
        + "right-click to move to Other";
      row.addEventListener("click", () => row.classList.toggle("open"));
      row.addEventListener("contextmenu", (ev) => {
        ev.preventDefault();
        if (otherTags.has(sig(e))) otherTags.delete(sig(e));
        else otherTags.add(sig(e));
        localStorage.setItem("sbOtherTags",
          JSON.stringify(Array.from(otherTags)));
        drawPop();
      });
      if (vid) {
        const bin = document.createElement("button");
        bin.textContent = "🗑";
        bin.title = "Mark voice " + vid[0] + " for deletion review — "
          + "broadcast issues / audio noise";
        bin.style.cssText = "margin-left:6px;background:none;border:none;"
          + "cursor:pointer;font-size:11px";
        bin.onclick = async (ev) => {
          ev.stopPropagation();
          try {
            await api.post("/api/voices/flag",
              {id: vid[0], why: e.text.slice(0, 110)});
            bin.textContent = "✓";
          } catch (err) { bin.title = err.message; }
        };
        row.appendChild(bin);
      }
      scroller.appendChild(row);
    });
    const freq = Object.entries(counts).sort((a, b) => b[1] - a[1])
      .slice(0, 7).map(([k, n]) => k + "×" + n).join(" · ");
    const foot = document.createElement("div");
    foot.className = "sb-foot";
    foot.textContent = "this session: " + (freq || "quiet") + " · "
      + ring.length + " events kept · right-click a row to file it "
      + "under Other";
    scroller.appendChild(foot);
    if (stickBottom) scroller.scrollTop = scroller.scrollHeight;
    else scroller.scrollTop = oldTop;      // stay where the reader was
    if (pop._grip) pop.appendChild(pop._grip);  // survives the rebuild
  }

  function restoreSize() {
    const saved = JSON.parse(
      localStorage.getItem("sbTermSize") || "null");
    if (saved) { pop.style.width = saved.w + "px";
      pop.style.height = saved.h + "px"; }
  }
  pop.addEventListener("mouseup", () => {
    localStorage.setItem("sbTermSize", JSON.stringify(
      {w: pop.offsetWidth, h: pop.offsetHeight}));
  });
  // #804: an explicit drag grip — native resize handles can be shy; this
  // one is 16px of unmissable corner, dragging as far as the window goes.
  const grip = document.createElement("div");
  grip.textContent = "◢";
  grip.style.cssText = "position:absolute;right:1px;bottom:1px;width:16px;"
    + "height:16px;cursor:nwse-resize;color:#5d6d7e;font-size:11px;"
    + "line-height:16px;text-align:center;user-select:none;z-index:2";
  grip.addEventListener("mousedown", (ev) => {
    ev.preventDefault();
    const sw = pop.offsetWidth, sh = pop.offsetHeight;
    const sx = ev.clientX, sy = ev.clientY;
    const move = (m) => {
      pop.style.width = Math.min(window.innerWidth * 0.98,
        Math.max(420, sw + (m.clientX - sx) * 2)) + "px";
      pop.style.height = Math.min(window.innerHeight * 0.94,
        Math.max(160, sh + (m.clientY - sy) * 2)) + "px";
    };
    const stop = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", stop);
      localStorage.setItem("sbTermSize", JSON.stringify(
        {w: pop.offsetWidth, h: pop.offsetHeight}));
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", stop);
  });
  pop._grip = grip;
  pop.appendChild(grip);

  // #791: the pointer over the popup means the operator is READING —
  // nothing may move, even at the tail. New entries wait in the ring
  // (the pill counts them); leaving the popup lets the flow resume.
  pop.addEventListener("mouseenter", () => { reading = true; });
  pop.addEventListener("mouseleave", () => {
    reading = false;
    if (open && stickBottom) { frozenAt = ring.length; drawPop(); }
  });
  line.addEventListener("click", () => {
    open = pop.style.display === "none";
    pop.style.display = open ? "flex" : "none";
    if (open) { restoreSize(); stickBottom = true; drawPop(); }
  });
  document.addEventListener("click", (ev) => {
    if (open && !pop.contains(ev.target) && ev.target !== line) {
      open = false;
      pop.style.display = "none";
    }
  });

  async function pollMarquee() {
    try {
      const got = await api.get("/api/models/loaded");
      const heavy = (got.procs || []).slice(0, 6)
        .map((p) => p.label + " " + p.rss_gb + "G"
          + (p.gpu_gb ? "+" + p.gpu_gb + "Ggpu" : "")).join("  ·  ");
      const perf = await api.get("/api/perf");
      marq.textContent =
        "DGX SPARK  ·  RAM " + (perf.ram_used_gb || "?") + "/"
        + (perf.ram_total_gb || "?") + "G (" + (perf.ram_pct || "?")
        + "%)  ·  heaviest: " + (heavy || "nothing notable")
        + (got.mem ? "  ·  " + got.mem : "");
    } catch { marq.textContent = "Spark stats unavailable — agent quiet"; }
    setTimeout(pollMarquee, 12000);
  }

  async function refreshLive() {
    const url = localStorage.getItem("pineLiveShareUrl") || "";
    liveBtn.classList.toggle("live", !!url);
    liveBtn.textContent = url ? "🔴 LIVE" : "📡";
    liveBtn.title = url
      ? "The station is LIVE — link copied on click · click to end it\n" + url
      : "Go LIVE — mint a public listen link for the station";
  }
  liveBtn.addEventListener("click", async () => {
    const url = localStorage.getItem("pineLiveShareUrl") || "";
    try {
      if (url) {
        if (!confirm("End the public broadcast? Every outstanding listen "
            + "link stops working.")) return;
        await api.post("/api/share/revoke", {all: true});
        localStorage.removeItem("pineLiveShareUrl");
      } else {
        const made = await api.post("/api/share", {scope: "listen"});
        const link = made.url || (made.urls && made.urls[0]
          && made.urls[0].url) || "";
        if (link) {
          localStorage.setItem("pineLiveShareUrl", link);
          await pineCopy(link);                              // #990
        }
      }
    } catch (err) { liveBtn.title = err.message; }
    refreshLive();
  });

  refreshLive();
  pollFeed();
  pollMarquee();
}
initStatusBar();

/* #800/#838: the sample extractor — paste a link (Ctrl+V over the 🎬
 * works), watch the fetch assemble as a rotating ASCII hexagon fed by
 * data streams, then scrub the VIDEO like a phone clip editor: IN/OUT
 * off the playhead, stack ranges, extract them all. Every cut whispers
 * its own words into a proposed name; the batch editor approves names
 * and the destination folder before anything joins the rotation. */
function initSamplePopup() {
  const btn = $("sampleBtn");
  const pop = $("samplePopup");
  if (!btn || !pop) return;
  let job = "", audioUrl = "", videoUrl = "", dur = 0, ranges = [],
      hoverBtn = false;
  const anim = { timer: 0, tick: 0, prog: 0, stage: "", note: "",
                 streams: [], el: null, bar: null };

  const fmt = (s) => Math.floor(s / 60) + ":" +
    String(Math.floor(s % 60)).padStart(2, "0");
  const escq = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;" }[c]));

  /* ---- the hexagon ---------------------------------------------------- */
  const HEX = [
    "      _________      ",
    "     /  _____  \\     ",
    "    /  /     \\  \\    ",
    "   |  |       |  |   ",
    "   |  |   @   |  |   ",
    "   |  |       |  |   ",
    "    \\  \\_____/  /    ",
    "     \\_________/     ",
  ];
  const HEXW = HEX[0].length, GUT = 15, W = HEXW + GUT * 2;
  const CELLS = [];
  HEX.forEach((line, r) => {
    for (let c = 0; c < line.length; c++) {
      if (line[c] !== " ") {
        const ang = Math.atan2(r - 3.5, c - HEXW / 2);
        CELLS.push({ r, c, ch: line[c], ang });
      }
    }
  });
  CELLS.sort((x, y) => x.ang - y.ang);
  const SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
  const CORE = "|/-\\";
  const DATA = "01#$%&*+=~<>";

  function hexFrame() {
    const t = anim.tick;
    const grid = Array.from({ length: HEX.length },
      () => Array(W).fill(" "));
    // the streams: characters coalescing into the form
    if (!anim.streams.length) {
      for (let k = 0; k < 16; k++) {
        anim.streams.push({
          r: Math.floor(Math.random() * HEX.length),
          x: Math.random() * GUT, left: k % 2 === 0,
          v: 0.5 + Math.random() * 1.2,
          ch: DATA[Math.floor(Math.random() * DATA.length)] });
      }
    }
    anim.streams.forEach((s) => {
      s.x += s.v;
      if (s.x >= GUT - 1) {           // it reaches the form: absorbed
        s.x = 0; s.r = Math.floor(Math.random() * HEX.length);
        s.ch = DATA[Math.floor(Math.random() * DATA.length)];
        s.v = 0.5 + Math.random() * 1.2;
      }
      const col = s.left ? Math.floor(s.x)
        : W - 1 - Math.floor(s.x);
      grid[s.r][col] = s.ch;
    });
    // the hexagon, assembling — reveal rotates with the tick so the
    // form appears to turn as it builds
    const shown = Math.max(3, Math.round(anim.prog * CELLS.length));
    for (let k = 0; k < shown; k++) {
      const cell = CELLS[(k + t) % CELLS.length];
      grid[cell.r][GUT + cell.c] =
        cell.ch === "@" ? CORE[t % CORE.length] : cell.ch;
    }
    // the core always spins
    grid[4][GUT + 10] = CORE[t % CORE.length];
    return grid.map((row) => row.join("")).join("\n");
  }

  function barLine() {
    const width = 26;
    const on = Math.round(anim.prog * width);
    return SPIN[anim.tick % SPIN.length] + " "
      + (anim.stage || "working") + " ▐"
      + "█".repeat(on) + "░".repeat(width - on) + "▌ "
      + Math.round(anim.prog * 100) + "%"
      + (anim.note ? "  · " + anim.note : "");
  }

  function animStart() {
    if (anim.timer) return;
    anim.timer = setInterval(() => {
      anim.tick += 1;
      if (anim.el && anim.el.isConnected) {
        anim.el.textContent = hexFrame();
        if (anim.bar) anim.bar.textContent = barLine();
      } else { animStop(); }
    }, 110);
  }
  function animStop() {
    if (anim.timer) { clearInterval(anim.timer); anim.timer = 0; }
    anim.streams = [];
  }

  /* ---- the popup ------------------------------------------------------ */
  function draw(stage, note) {
    animStop();
    pop.innerHTML = "<b>🎬 Add a sample</b>";
    const urlRow = document.createElement("div");
    urlRow.className = "sp-row";
    urlRow.innerHTML = "<input type='text' id='spUrl' placeholder='paste a "
      + "YouTube / any video link…'><button id='spFetch'>Fetch</button>"
      + "<button id='spClose'>✕</button>";
    pop.appendChild(urlRow);
    if (note && stage !== "fetching") {
      const st = document.createElement("div");
      st.className = "muted";
      st.textContent = note;
      pop.appendChild(st);
    }
    if (stage === "fetching") {
      const hex = document.createElement("pre");
      hex.className = "sp-hex";
      const bar = document.createElement("div");
      bar.className = "sp-hexbar";
      pop.appendChild(hex);
      pop.appendChild(bar);
      anim.el = hex; anim.bar = bar;
      anim.note = note || "";
      animStart();
    }
    if (stage === "ready") {
      let media;
      if (videoUrl) {
        media = document.createElement("video");
        media.controls = true; media.playsInline = true;
        media.preload = "metadata";
        media.style.cssText = "width:100%;max-height:280px;background:#000;"
          + "border-radius:8px";
        media.src = videoUrl;
        media.onerror = () => {          // no picture kept — audio still cuts
          videoUrl = "";
          draw("ready", "no video for this one — cutting by ear");
        };
      } else {
        media = document.createElement("audio");
        media.controls = true;
        media.src = audioUrl;
      }
      media.addEventListener("loadedmetadata", () => {
        dur = media.duration || 0; paint();
      });
      pop.appendChild(media);
      const bar = document.createElement("div");
      bar.className = "sp-bar";
      bar.onclick = (ev) => {
        const r = bar.getBoundingClientRect();
        media.currentTime = dur * (ev.clientX - r.left) / r.width;
      };
      pop.appendChild(bar);
      const tools = document.createElement("div");
      tools.className = "sp-row";
      tools.innerHTML = "<button id='spIn'>⟦ IN at playhead</button>"
        + "<button id='spOut'>OUT at playhead ⟧</button>"
        + "<button id='spPrev'>▶ preview range</button>"
        + "<button id='spAdd'>+ keep range, start another</button>"
        + "<button id='spCut' class='primary'>✂ Extract all</button>";
      pop.appendChild(tools);
      const list = document.createElement("div");
      list.id = "spList";
      pop.appendChild(list);
      let a = 0, b = 0, stopAt = 0;
      function paint() {
        bar.innerHTML = "";
        ranges.concat(b > a ? [{a, b}] : []).forEach((r) => {
          const i = document.createElement("i");
          i.style.left = (100 * r.a / (dur || 1)) + "%";
          i.style.width = (100 * (r.b - r.a) / (dur || 1)) + "%";
          bar.appendChild(i);
        });
        list.innerHTML = ranges.map((r, n) =>
          "<div class='sp-range'>" + (n + 1) + ". " + fmt(r.a) + " → "
          + fmt(r.b) + " <input type='text' placeholder='name it — or "
          + "leave blank and it names itself from the words…' "
          + "data-n='" + n + "' value='" + escq(r.name) + "'>"
          + "<button data-x='" + n + "'>✕</button></div>").join("")
          + (b > a ? "<div class='sp-range muted'>working range: "
             + fmt(a) + " → " + fmt(b) + "</div>" : "");
        list.querySelectorAll("input").forEach((inp) => {
          inp.oninput = () => { ranges[+inp.dataset.n].name = inp.value; };
        });
        list.querySelectorAll("button[data-x]").forEach((x) => {
          x.onclick = () => { ranges.splice(+x.dataset.x, 1); paint(); };
        });
      }
      media.addEventListener("timeupdate", () => {
        if (stopAt && media.currentTime >= stopAt) {
          media.pause(); stopAt = 0;
        }
      });
      $("spIn").onclick = () => { a = media.currentTime; paint(); };
      $("spOut").onclick = () => { b = media.currentTime; paint(); };
      $("spPrev").onclick = () => {
        if (b > a) { media.currentTime = a; stopAt = b; media.play(); }
      };
      $("spAdd").onclick = () => {
        if (b > a) { ranges.push({a, b}); a = b = 0; paint(); }
      };
      $("spCut").onclick = async () => {
        if (b > a) { ranges.push({a, b}); a = b = 0; }
        if (!ranges.length) return;
        $("spCut").textContent = "cutting + naming…";
        $("spCut").disabled = true;
        try {
          const got = await api.post("/api/samples/extract",
            {job_id: job, ranges, stage_only: true});
          drawBatch(got.staged || []);
          ranges = [];
        } catch (err) {
          $("spCut").disabled = false;
          $("spCut").textContent = "✂ Extract all";
          const st = document.createElement("div");
          st.className = "muted";
          st.textContent = err.message;
          pop.appendChild(st);
        }
      };
      paint();
    }
    $("spClose").onclick = () => {
      animStop(); pop.style.display = "none";
    };
    $("spFetch").onclick = () => fetchUrl($("spUrl").value.trim());
    if (stage === "idle") $("spUrl").focus();
  }

  /* ---- the batch approval editor (#838) ------------------------------- */
  function drawBatch(rows) {
    animStop();
    pop.innerHTML = "<b>🎬 Approve the cuts</b>";
    const head = document.createElement("div");
    head.className = "muted";
    head.textContent = rows.length + " cut(s) staged — each named from "
      + "its own words. Fix any name, pick the folder, save the batch. "
      + "Nothing reaches the rotation until you approve it.";
    pop.appendChild(head);
    const folderRow = document.createElement("div");
    folderRow.className = "sp-row";
    folderRow.innerHTML = "<span class='muted'>folder under the SFX "
      + "root:</span> <input type='text' id='spFolder' "
      + "style='flex:1;min-width:120px'>"
      + "<button id='spBack'>‹ back</button>"
      + "<button id='spClose'>✕</button>";
    pop.appendChild(folderRow);
    const fInp = folderRow.querySelector("#spFolder");
    fInp.value = localStorage.getItem("pineSampleFolder") || "Samples";
    const list = document.createElement("div");
    list.className = "sp-batch";
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "sp-range";
      row.dataset.id = r.id;
      const play = document.createElement("audio");
      play.controls = true; play.preload = "none";
      play.src = desktopMusicUrl(r.url);
      play.style.cssText = "height:26px;width:170px;flex:0 0 auto";
      row.appendChild(play);
      const name = document.createElement("input");
      name.type = "text";
      name.value = r.name || "";
      name.style.cssText = "flex:1;min-width:0";
      name.title = r.words ? "it heard: " + r.words : "no words heard";
      row.appendChild(name);
      const secs = document.createElement("span");
      secs.className = "muted";
      secs.textContent = (r.seconds || 0) + "s";
      row.appendChild(secs);
      const x = document.createElement("button");
      x.textContent = "✕";
      x.title = "Drop this cut — it will not be saved";
      x.onclick = () => row.remove();
      row.appendChild(x);
      list.appendChild(row);
    });
    pop.appendChild(list);
    const save = document.createElement("button");
    save.className = "primary";
    save.textContent = "💾 Save the batch as named";
    save.onclick = async () => {
      const items = Array.from(list.querySelectorAll(".sp-range"))
        .map((row) => ({ id: row.dataset.id,
          name: row.querySelector("input").value.trim() }));
      if (!items.length) { draw("idle", "nothing left to save"); return; }
      save.disabled = true; save.textContent = "saving…";
      try {
        const folder = fInp.value.trim() || "Samples";
        localStorage.setItem("pineSampleFolder", folder);
        const got = await api.post("/api/samples/commit", {items, folder});
        draw("done", "✓ " + got.saved.length + " sample(s) saved into "
          + got.folder + " — the DJs have them in rotation now: "
          + got.saved.join(", "));
      } catch (err) {
        save.disabled = false;
        save.textContent = "💾 Save the batch as named";
        head.textContent = err.message;
      }
    };
    pop.appendChild(save);
    folderRow.querySelector("#spBack").onclick = () =>
      draw("ready", "the staged cuts are still on the shelf — extract "
        + "again or approve them later");
    folderRow.querySelector("#spClose").onclick = () => {
      pop.style.display = "none";
    };
  }

  async function fetchUrl(url) {
    if (!url) return;
    pop.style.display = "flex";
    anim.prog = 0; anim.stage = "reaching out";
    draw("fetching", "");
    $("spUrl").value = url;
    try {
      job = (await api.post("/api/samples/fetch", {url})).job_id;
      const t0 = Date.now();
      while (Date.now() - t0 < 900000) {
        await new Promise((r) => setTimeout(r, 2500));
        let st = {};
        try { st = await api.get("/api/samples/job/" + job); }
        catch { continue; }
        if (st.stage === "done" && st.audio) {
          audioUrl = desktopMusicUrl(st.audio);
          videoUrl = st.video ? desktopMusicUrl(st.video) : "";
          ranges = [];
          anim.prog = 1;
          draw("ready", (st.title || "ready") + " — set IN/OUT off the "
            + "playhead, stack ranges, extract them all at once.");
          return;
        }
        if (st.stage === "error") {
          draw("idle", st.error || "that link would not fetch"); return;
        }
        anim.stage = st.stage || "working";
        anim.prog = Math.max(anim.prog,
          Math.min(0.99, Number(st.progress) || 0));
        anim.note = st.note || "";
        if (!anim.timer || !anim.el || !anim.el.isConnected) {
          draw("fetching", "");
        }
      }
      draw("idle", "that took too long — try again");
    } catch (err) { draw("idle", err.message); }
  }

  // #808: the sidebar tab opens the same popup as the corner icon.
  const railTab = $("sampleTabBtn");
  if (railTab) {
    railTab.addEventListener("click", () => {
      pop.style.display = "flex";
      draw("idle", "paste a link — or Ctrl+V one over the 🎬");
    });
    railTab.addEventListener("mouseenter", () => { hoverBtn = true; });
    railTab.addEventListener("mouseleave", () => { hoverBtn = false; });
  }
  btn.addEventListener("mouseenter", () => { hoverBtn = true; });
  btn.addEventListener("mouseleave", () => { hoverBtn = false; });
  btn.addEventListener("click", () => {
    pop.style.display = "flex";
    draw("idle", "paste a link — or Ctrl+V one anywhere over the 🎬");
  });
  document.addEventListener("paste", (ev) => {
    const text = (ev.clipboardData || {}).getData
      ? ev.clipboardData.getData("text") : "";
    if (hoverBtn && /https?:\/\/|youtu/i.test(text)) fetchUrl(text.trim());
  });
}
initSamplePopup();

/* #836: the crystal CABINET — the 🔮 opens a draggable, resizable
 * popup: pick which crystal rides the airwaves, set how hard it
 * presses (strength), choose which album-minds it draws from, retint
 * its flavor line, or shatter it. #794: 📜 opens a chunk reader.
 * #797: the reader lists every SOURCE, each expandable to its captured
 * data, beside a rotating three.js tower of hexagons — one hex per
 * chunk — that lights up wherever the data point you are exploring
 * lives. #795: any document opens in full from the sources list. */
function initCrystalBtn() {
  const btn = $("crystalBtn");
  const pop = $("crystalPopup");
  if (!btn || !pop) return;
  let cache = { crystals: [], extractions: {} };
  let mindsAll = [];
  let mode = "cards";
  let threeP = null;
  let tower = null;

  function loadThree() {
    if (window.THREE) return Promise.resolve();
    if (threeP) return threeP;
    threeP = new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = ((config && config.baseUrl) || "http://127.0.0.1:8096")
        + "/vendor/three.min.js";
      s.onload = () => res();
      s.onerror = () => { threeP = null; rej(new Error("no three.js")); };
      document.head.appendChild(s);
    });
    return threeP;
  }

  function towerStop() {
    if (!tower) return;
    cancelAnimationFrame(tower.raf);
    try { tower.renderer.dispose(); } catch { /* gone */ }
    tower = null;
  }

  /* #797: the tower — chunks stacked as hexagons climbing a cylinder,
   * turning slowly; big minds bucket several chunks per hex. */
  async function towerStart(canvas, N) {
    towerStop();
    try {
      await loadThree();
    } catch (err) {
      // #806: "I'm not seeing any of that" — a silent three.js failure
      // looked like the tower did not exist. Now the canvas says why.
      const note = document.createElement("div");
      note.className = "muted";
      note.style.cssText = "width:190px;flex:none;padding:10px;"
        + "font-size:11px";
      note.textContent = "the tower could not rise: " + err.message
        + " — is the agent reachable? It serves three.js at "
        + "/vendor/three.min.js.";
      canvas.replaceWith(note);
      return;
    }
    const T = window.THREE;
    // #821: every data point is a HEXAGON in an interlocked honeycomb.
    // Each storey is a full hex-grid disc; the discs stack into the
    // tower, so the base is a wide slab instead of a thin cylinder.
    const CAP = 6200, CH = 2.35, S = 2.55;   // cell circumradius
    const scale = Math.max(1, Math.ceil((N || 1) / CAP));
    const cells = Math.max(1, Math.ceil((N || 1) / scale));
    // rings k give 1+3k(k+1) hexes a disc — take the smallest disc that
    // keeps the tower under ~34 storeys, capped at 8 rings (217/storey).
    let K = 1;
    while (K < 8 && cells / (1 + 3 * K * (K + 1)) > 34) K++;
    const spots = [[0, 0]];                  // spiral: centre out
    for (let k = 1; k <= K; k++) {
      let q = k, r = 0;
      const dirs = [[-1, 1], [-1, 0], [0, -1], [1, -1], [1, 0], [0, 1]];
      for (const d of dirs) {
        for (let s = 0; s < k; s++) {
          spots.push([q, r]); q += d[0]; r += d[1];
        }
      }
    }
    const PER = spots.length;
    const layers = Math.ceil(cells / PER);
    const w = Math.max(190, Math.min(300, Math.floor(
      (canvas.parentElement ? canvas.parentElement.clientWidth : 560)
      * 0.42)));
    canvas.style.width = w + "px";
    const h = Math.max(300, canvas.parentElement
      ? canvas.parentElement.clientHeight - 2 : 420);
    const renderer = new T.WebGLRenderer(
      { canvas, antialias: true, alpha: true });
    renderer.setSize(w, h, false);
    const scene = new T.Scene();
    const camera = new T.PerspectiveCamera(50, w / h, 0.1, 6000);
    scene.add(new T.AmbientLight(0xffffff, 0.55));
    const sun = new T.DirectionalLight(0xc9a0ff, 1.1);
    sun.position.set(60, 120, 80);
    scene.add(sun);
    const geo = new T.CylinderGeometry(S, S, CH * 0.92, 6);
    const mat = new T.MeshStandardMaterial(
      { metalness: 0.35, roughness: 0.45 });
    const mesh = new T.InstancedMesh(geo, mat, cells);
    const dummy = new T.Object3D();
    const dim = new T.Color(0x4b2a6e);
    for (let i = 0; i < cells; i++) {
      const layer = Math.floor(i / PER);
      const qr = spots[i % PER];
      // flat-side-to-flat-side spacing: tangent neighbours, no gaps
      dummy.position.set(S * 1.5 * qr[0], layer * CH + CH / 2,
        S * Math.sqrt(3) * (qr[1] + qr[0] / 2));
      dummy.rotation.y = Math.PI / 6;   // faces mate across the lattice
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, dim);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    const group = new T.Group();
    group.add(mesh);
    scene.add(group);
    const height = layers * CH;
    const baseR = S * Math.sqrt(3) * (K + 1);
    tower = { renderer, scene, camera, mesh, group, raf: 0, scale,
              cells, PER, CH, height, camY: height * 0.35,
              targetY: height * 0.35, yaw: 0, pitch: 0.34,
              dist: Math.max(baseR * 3.2, height * 0.95), panX: 0,
              auto: true };
    // #821: orbit controls — drag turns, wheel zooms, shift/right-drag
    // pans. The self-spin stops at the first touch of the hand.
    let drag = null;
    canvas.style.touchAction = "none";
    canvas.onpointerdown = (ev) => {
      drag = { x: ev.clientX, y: ev.clientY,
               pan: ev.button === 2 || ev.shiftKey };
      if (tower) tower.auto = false;
      try { canvas.setPointerCapture(ev.pointerId); } catch { /* old */ }
    };
    canvas.onpointermove = (ev) => {
      if (!drag || !tower) return;
      const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      drag.x = ev.clientX; drag.y = ev.clientY;
      if (drag.pan) {
        tower.panX -= dx * tower.dist * 0.0014;
        tower.targetY += dy * tower.dist * 0.0014;
        tower.camY = tower.targetY;      // a pan lands, it never chases
      } else {
        tower.yaw += dx * 0.008;
        tower.pitch = Math.max(-1.2, Math.min(1.35,
          tower.pitch + dy * 0.006));
      }
    };
    canvas.onpointerup = () => { drag = null; };
    canvas.oncontextmenu = (ev) => ev.preventDefault();
    canvas.onwheel = (ev) => {
      ev.preventDefault();
      if (!tower) return;
      tower.auto = false;
      tower.dist = Math.max(baseR * 1.3, Math.min(baseR * 40,
        tower.dist * (ev.deltaY > 0 ? 1.12 : 0.9)));
    };
    (function spin() {
      if (!tower) return;
      tower.raf = requestAnimationFrame(spin);
      if (tower.auto) tower.yaw += 0.004;
      tower.camY += (tower.targetY - tower.camY) * 0.06;
      const cy = tower.camY + tower.height * 0.06;
      const cp = Math.cos(tower.pitch) * tower.dist;
      camera.position.set(tower.panX + Math.sin(tower.yaw) * cp,
        cy + Math.sin(tower.pitch) * tower.dist,
        Math.cos(tower.yaw) * cp);
      camera.lookAt(tower.panX, cy, 0);
      renderer.render(scene, camera);
    })();
  }

  /* Light the hexes of the data being explored; `focus` is the ONE
   * point in hand — the camera rides up or down the tower to it. */
  function towerPaint(indices, focus) {
    if (!tower || !window.THREE) return;
    const T = window.THREE;
    const dim = new T.Color(0x4b2a6e);
    const lit = new T.Color(0xc98fe0);
    const hot = new T.Color(0xffffff);
    for (let i = 0; i < tower.cells; i++) {
      tower.mesh.setColorAt(i, dim);
    }
    (indices || []).forEach((gi) => {
      tower.mesh.setColorAt(Math.min(tower.cells - 1,
        Math.floor(gi / tower.scale)), lit);
    });
    if (focus != null) {
      const c = Math.min(tower.cells - 1,
        Math.floor(focus / tower.scale));
      tower.mesh.setColorAt(c, hot);
      tower.targetY = Math.floor(c / tower.PER) * tower.CH;
    }
    if (tower.mesh.instanceColor) {
      tower.mesh.instanceColor.needsUpdate = true;
    }
  }

  async function pull() {
    try {
      const d = await api.get("/api/crystals");
      cache = { crystals: d.crystals || [],
                extractions: d.extractions || {} };
      const m = await api.get("/api/speakbox/minds");
      mindsAll = (m.minds || []).filter((x) => x.id !== "main");
    } catch { /* agent quiet */ }
  }

  function paintBtn() {
    const on = cache.crystals.filter((c) => c.on);
    btn.classList.toggle("on", on.length > 0);
    btn.title = on.length
      ? "The universe is tinted: " + on.map((c) => c.name).join(", ")
        + " — click to open the crystal cabinet"
      : "Crystals — open the cabinet, choose what tints the universe";
  }

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function chunkSum(c) {
    return Object.values(c.chunks || {})
      .reduce((acc, v) => acc + (v | 0), 0);
  }

  async function save(cid, body) {
    try {
      await api.post("/api/crystals", Object.assign({ id: cid }, body));
    } catch (err) { console.warn("crystal save", err); }
    await pull(); paintBtn(); draw();
  }

  function popRemember() {
    try {
      localStorage.setItem("crystalPopBox", JSON.stringify({
        left: pop.offsetLeft, top: pop.offsetTop,
        w: pop.offsetWidth, h: pop.offsetHeight }));
    } catch { /* full quota keeps the cabinet */ }
  }

  function popRestore() {
    let bag = {};
    try {
      bag = JSON.parse(localStorage.getItem("crystalPopBox") || "{}")
        || {};
    } catch { bag = {}; }
    if (Number(bag.w) > 0) {
      pop.style.transform = "none";
      pop.style.width = Math.min(bag.w, window.innerWidth - 16) + "px";
      pop.style.height = Math.max(220, Math.min(bag.h || 480,
        window.innerHeight - 16)) + "px";
      pop.style.maxHeight = "none";
      pop.style.left = Math.max(0, Math.min(bag.left || 40,
        window.innerWidth - 80)) + "px";
      pop.style.top = Math.max(0, Math.min(bag.top || 40,
        window.innerHeight - 80)) + "px";
    }
  }

  function dragBy(handle) {
    handle.addEventListener("mousedown", (ev) => {
      if (ev.target.closest("button,input,select")) return;
      const r = pop.getBoundingClientRect();
      const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
      pop.style.transform = "none";
      function move(e) {
        pop.style.left = Math.max(0, e.clientX - dx) + "px";
        pop.style.top = Math.max(0, e.clientY - dy) + "px";
      }
      function up() {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        popRemember();
      }
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  }

  /* #813: a floating DATA WINDOW — its own draggable, resizable
   * frame over everything, so several sources can be open side by
   * side for analysis. */
  let dataWinAt = 0;
  function winGrips(el) {
    [["n", "top:-3px;left:14px;right:14px;height:9px;cursor:ns-resize"],
     ["s", "bottom:-3px;left:14px;right:14px;height:9px;cursor:ns-resize"],
     ["w", "left:-3px;top:14px;bottom:14px;width:9px;cursor:ew-resize"],
     ["e", "right:-3px;top:14px;bottom:14px;width:9px;cursor:ew-resize"],
     ["nw", "top:-4px;left:-4px;width:16px;height:16px;cursor:nwse-resize"],
     ["ne", "top:-4px;right:-4px;width:16px;height:16px;cursor:nesw-resize"],
     ["sw", "bottom:-4px;left:-4px;width:16px;height:16px;cursor:nesw-resize"],
     ["se", "bottom:-4px;right:-4px;width:16px;height:16px;cursor:nwse-resize"],
    ].forEach(([dir, css]) => {
      const grip = document.createElement("div");
      grip.style.cssText = "position:absolute;z-index:9;" + css;
      grip.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const r = el.getBoundingClientRect();
        const sx = ev.clientX, sy = ev.clientY;
        const move = (e) => {
          const dx = e.clientX - sx, dy = e.clientY - sy;
          let left = r.left, top = r.top;
          let width = r.width, height = r.height;
          if (dir.indexOf("e") >= 0) width = r.width + dx;
          if (dir.indexOf("s") >= 0) height = r.height + dy;
          if (dir.indexOf("w") >= 0) width = r.width - dx;
          if (dir.indexOf("n") >= 0) height = r.height - dy;
          width = Math.max(320, Math.min(width, window.innerWidth - 12));
          height = Math.max(200, Math.min(height,
            window.innerHeight - 12));
          if (dir.indexOf("w") >= 0) left = r.right - width;
          if (dir.indexOf("n") >= 0) top = r.bottom - height;
          el.style.width = width + "px";
          el.style.height = height + "px";
          el.style.left = Math.max(0, left) + "px";
          el.style.top = Math.max(0, top) + "px";
        };
        const up = () => {
          document.removeEventListener("pointermove", move);
          document.removeEventListener("pointerup", up);
        };
        document.addEventListener("pointermove", move);
        document.addEventListener("pointerup", up);
      });
      el.appendChild(grip);
    });
  }

  function dataWin(rid, file, kind) {
    const win = document.createElement("div");
    win.className = "cp-datawin";
    dataWinAt = (dataWinAt + 1) % 8;
    win.style.left = (110 + dataWinAt * 30) + "px";
    win.style.top = (80 + dataWinAt * 26) + "px";
    const head = document.createElement("div");
    head.className = "cp-head";
    head.innerHTML = "<b>" + (kind === "doc" ? "📄 " : "📜 ")
      + esc(file) + "</b><span class='muted cp-count'></span>"
      + "<button class='cp-x'>✕</button>";
    win.appendChild(head);
    head.addEventListener("mousedown", (ev) => {
      if (ev.target.closest("button,input")) return;
      const r = win.getBoundingClientRect();
      const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
      const move = (e) => {
        win.style.left = Math.max(0, e.clientX - dx) + "px";
        win.style.top = Math.max(0, e.clientY - dy) + "px";
      };
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    const body = document.createElement("div");
    body.className = "cp-left";
    body.style.flex = "1";
    win.appendChild(body);
    document.body.appendChild(win);
    winGrips(win);
    head.querySelector(".cp-x").onclick = () => win.remove();

    if (kind === "doc") {
      body.innerHTML = "<span class='muted'>opening…</span>";
      api.get("/api/speakbox/" + encodeURIComponent(file) + "?mind="
        + encodeURIComponent(rid)).then((d) => {
        body.innerHTML = "";
        head.querySelector(".cp-count").textContent =
          (d.mind ? "lives in " + d.mind + " · " : "")
          + (d.text || "").length.toLocaleString() + " chars";
        const txt = document.createElement("div");
        txt.className = "cp-doc";
        txt.textContent = d.text || "(empty)";
        body.appendChild(txt);
      }).catch((err) => { body.textContent = err.message; });
      return;
    }
    let offset = 0, filter = "";
    const bar = document.createElement("div");
    bar.className = "cp-row";
    bar.innerHTML = "<input type='text' placeholder='filter the "
      + "chunks…' style='flex:1'>";
    const q = bar.querySelector("input");
    q.onchange = () => { filter = q.value.trim(); offset = 0;
      load(true); };
    body.appendChild(bar);
    const list = document.createElement("div");
    list.className = "cp-chunks";
    body.appendChild(list);
    const more = document.createElement("button");
    more.textContent = "more ↓";
    more.style.display = "none";
    more.onclick = () => { offset += 200; load(false); };
    body.appendChild(more);
    async function load(reset) {
      if (reset) list.innerHTML = "<span class='muted'>reading…</span>";
      more.disabled = true;
      try {
        const d = await api.get("/api/speakbox/minds/"
          + encodeURIComponent(rid) + "/chunks?offset=" + offset
          + "&limit=200&file=" + encodeURIComponent(file)
          + (filter ? "&q=" + encodeURIComponent(filter) : ""));
        if (reset) list.innerHTML = "";
        const page = d.chunks || [];
        head.querySelector(".cp-count").textContent =
          (d.total || 0).toLocaleString() + " chunks";
        page.forEach((c) => {
          const row = document.createElement("div");
          row.className = "cp-chunk";
          row.innerHTML = "<span class='cp-file'>#" + c.i + "</span>"
            + esc(c.text);
          // the tower in the reader lights up where this point lives
          row.onclick = () => towerPaint(page.map((x) => x.i), c.i);
          list.appendChild(row);
        });
        if (!d.total) {
          list.innerHTML =
            "<span class='muted'>nothing captured here yet</span>";
        }
        more.style.display =
          (offset + 200 < d.total) ? "inline-block" : "none";
      } catch (err) { list.textContent = err.message; }
      more.disabled = false;
    }
    load(true);
  }

  /* #807: RESIZE FROM ANY EDGE OR CORNER — eight pointer grips that
   * survive every repaint (draw/openMind wipe innerHTML; the grips are
   * re-appended after each rebuild). Reactive: the box follows the
   * pointer directly, no native-resize fights. */
  function ensureGrips() {
    if (!pop._grips) {
      pop._grips = [
        ["n", "top:-3px;left:14px;right:14px;height:9px;cursor:ns-resize"],
        ["s", "bottom:-3px;left:14px;right:14px;height:9px;cursor:ns-resize"],
        ["w", "left:-3px;top:14px;bottom:14px;width:9px;cursor:ew-resize"],
        ["e", "right:-3px;top:14px;bottom:14px;width:9px;cursor:ew-resize"],
        ["nw", "top:-4px;left:-4px;width:16px;height:16px;cursor:nwse-resize"],
        ["ne", "top:-4px;right:-4px;width:16px;height:16px;cursor:nesw-resize"],
        ["sw", "bottom:-4px;left:-4px;width:16px;height:16px;cursor:nesw-resize"],
        ["se", "bottom:-4px;right:-4px;width:16px;height:16px;cursor:nwse-resize"],
      ].map(([dir, css]) => {
        const grip = document.createElement("div");
        grip.style.cssText = "position:absolute;z-index:9;" + css;
        grip.addEventListener("pointerdown", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const r = pop.getBoundingClientRect();
          const sx = ev.clientX, sy = ev.clientY;
          const move = (e) => {
            const dx = e.clientX - sx, dy = e.clientY - sy;
            let left = r.left, top = r.top;
            let width = r.width, height = r.height;
            if (dir.indexOf("e") >= 0) width = r.width + dx;
            if (dir.indexOf("s") >= 0) height = r.height + dy;
            if (dir.indexOf("w") >= 0) width = r.width - dx;
            if (dir.indexOf("n") >= 0) height = r.height - dy;
            width = Math.max(340, Math.min(width,
              window.innerWidth - 12));
            height = Math.max(220, Math.min(height,
              window.innerHeight - 12));
            if (dir.indexOf("w") >= 0) left = r.right - width;
            if (dir.indexOf("n") >= 0) top = r.bottom - height;
            pop.style.transform = "none";
            pop.style.width = width + "px";
            pop.style.height = height + "px";
            pop.style.maxHeight = "none";
            pop.style.left = Math.max(0, left) + "px";
            pop.style.top = Math.max(0, top) + "px";
          };
          const up = () => {
            document.removeEventListener("pointermove", move);
            document.removeEventListener("pointerup", up);
            popRemember();
          };
          document.addEventListener("pointermove", move);
          document.addEventListener("pointerup", up);
        });
        return grip;
      });
    }
    pop._grips.forEach((g) => pop.appendChild(g));
  }

  /* #794/#795/#797: the reader — sources first, each expandable into
   * its chunks or the whole document, the tower riding alongside. */
  function openMind(minds, title) {
    minds = (minds || []).filter(Boolean);
    if (!minds.length) return;
    mode = "viewer";
    let rid = minds[0];
    pop.innerHTML = "";
    const head = document.createElement("div");
    head.className = "cp-head";
    head.innerHTML = "<button class='cp-back'>‹ back</button><b>📜 "
      + esc(title) + "</b><span class='muted cp-count'></span>"
      + "<button class='cp-x'>✕</button>";
    pop.appendChild(head);
    dragBy(head);
    head.querySelector(".cp-back").onclick = () => draw();
    head.querySelector(".cp-x").onclick = () => {
      pop.style.display = "none"; towerStop(); mode = "cards";
    };
    if (minds.length > 1) {
      const sel = document.createElement("select");
      minds.forEach((m) => {
        const o = document.createElement("option");
        o.value = m;
        const row = mindsAll.find((x) => x.id === m);
        o.textContent = (row && row.name) || m;
        sel.appendChild(o);
      });
      sel.onchange = () => { rid = sel.value; sources(); };
      head.insertBefore(sel, head.querySelector(".cp-x"));
    }
    const body = document.createElement("div");
    body.className = "cp-body";
    const left = document.createElement("div");
    left.className = "cp-left";
    const canvas = document.createElement("canvas");
    canvas.id = "cpTower";
    canvas.title = "the mind as a honeycomb tower — every hexagon "
      + "is a data point; the white one is the point you are exploring. "
      + "Drag to turn, wheel to zoom, shift-drag or right-drag to pan";
    body.appendChild(left);
    body.appendChild(canvas);
    pop.appendChild(body);

    const WHO_ICON = { host: "🎙", cohost: "🎤", sfxguy: "🤠",
                       caller: "☎" };
    async function siphons() {
      // #813: the influence ring says who is siphoning which document
      // RIGHT NOW — badge the rows, and keep badging as they jump.
      try {
        const d = await api.get("/api/crystals/influence");
        const cutoff = Date.now() / 1000 - 360;
        const byFile = new Map();
        (d.rows || []).forEach((r) => {
          if (r.ts < cutoff) return;
          const set = byFile.get(r.file) || new Set();
          (r.targets || []).forEach((t) => set.add(t));
          byFile.set(r.file, set);
        });
        left.querySelectorAll(".cp-source").forEach((row) => {
          const f = row.dataset.file || "";
          let badge = row.querySelector(".cp-siphon");
          const set = byFile.get(f);
          if (set && set.size) {
            if (!badge) {
              badge = document.createElement("span");
              badge.className = "cp-siphon";
              badge.title = "being siphoned RIGHT NOW by: "
                + Array.from(set).join(", ");
              row.insertBefore(badge, row.firstChild);
            }
            badge.textContent = Array.from(set)
              .map((t) => WHO_ICON[t] || "•").join("");
          } else if (badge) {
            badge.remove();
          }
        });
      } catch { /* agent quiet */ }
    }
    if (!pop._siphonTimer) {
      pop._siphonTimer = setInterval(() => {
        if (mode === "viewer" && pop.style.display !== "none") siphons();
      }, 5000);
    }
    async function sources() {
      left.innerHTML = "<span class='muted'>reading the sources…</span>";
      try {
        const d = await api.get("/api/speakbox/minds/"
          + encodeURIComponent(rid) + "/sources");
        head.querySelector(".cp-count").textContent =
          (d.name || rid) + " · " + (d.all || 0).toLocaleString()
          + " chunks";
        towerStart(canvas, d.all || 0);
        left.innerHTML = "";
        if (!(d.sources || []).length) {
          left.innerHTML = "<span class='muted'>this mind is empty — "
            + "nothing has been embedded into it yet</span>";
        }
        // #806: grouped by WHO the capture came from — the leading name
        // of the file — instead of one flat 800-row wall.
        const groups = new Map();
        (d.sources || []).forEach((s) => {
          const m = String(s.file || "").match(/^[A-Za-z]+/);
          const who = (m ? m[0] : "other").toLowerCase();
          if (!groups.has(who)) groups.set(who, []);
          groups.get(who).push(s);
        });
        Array.from(groups.keys()).sort().forEach((who) => {
          const rows = groups.get(who);
          const box = document.createElement("details");
          box.className = "cp-srcgroup";
          box.open = groups.size <= 2;
          const cap = document.createElement("summary");
          const total = rows.reduce((a, s) => a + (s.chunks | 0), 0);
          cap.textContent = who + " \u00b7 " + rows.length
            + " source(s) \u00b7 " + total.toLocaleString() + " chunks";
          box.appendChild(cap);
          rows.sort((a, b) => String(a.file).localeCompare(
            String(b.file)));
          rows.forEach((s) => {
            const row = document.createElement("div");
            row.className = "cp-source";
            row.dataset.file = s.file;
            row.innerHTML = "<span class='cp-src-name'>" + esc(s.file)
              + "</span><i>" + s.chunks.toLocaleString() + "</i>"
              + "<button class='cp-src-doc' title='open the whole "
              + "document'>📄</button>"
              + "<button class='cp-src-ch' title='scroll its captured "
              + "chunks'>📜</button>";
            const range = [];
            for (let k = 0; k < Math.min(s.chunks, 600); k++) {
              range.push(s.first + k);
            }
            row.addEventListener("mouseenter",
              () => towerPaint(range, s.first));
            // #813: each opens its own floating window — several
            // sources side by side, the reader stays put.
            row.querySelector(".cp-src-doc").onclick =
              () => dataWin(rid, s.file, "doc");
            row.querySelector(".cp-src-ch").onclick =
              () => dataWin(rid, s.file, "chunks");
            box.appendChild(row);
          });
          left.appendChild(box);
        });
      } catch (err) { left.textContent = err.message; }
    }

    async function chunks(file) {
      let offset = 0, filter = "";
      left.innerHTML = "";
      const bar = document.createElement("div");
      bar.className = "cp-row";
      bar.innerHTML = "<button class='cp-up'>‹ sources</button>"
        + "<input type='text' placeholder='filter…' style='flex:1'>";
      bar.querySelector(".cp-up").onclick = () => sources();
      const q = bar.querySelector("input");
      q.onchange = () => { filter = q.value.trim(); offset = 0;
        load(true); };
      left.appendChild(bar);
      const list = document.createElement("div");
      list.className = "cp-chunks";
      left.appendChild(list);
      const more = document.createElement("button");
      more.textContent = "more ↓";
      more.style.display = "none";
      more.onclick = () => { offset += 200; load(false); };
      left.appendChild(more);
      async function load(reset) {
        if (reset) list.innerHTML = "<span class='muted'>reading…</span>";
        more.disabled = true;
        try {
          const d = await api.get("/api/speakbox/minds/"
            + encodeURIComponent(rid) + "/chunks?offset=" + offset
            + "&limit=200&file=" + encodeURIComponent(file || "")
            + (filter ? "&q=" + encodeURIComponent(filter) : ""));
          if (reset) list.innerHTML = "";
          const page = d.chunks || [];
          page.forEach((c) => {
            const row = document.createElement("div");
            row.className = "cp-chunk";
            row.innerHTML = "<span class='cp-file'>#" + c.i + " · "
              + esc(c.file) + "</span>" + esc(c.text);
            row.onclick = () => {
              towerPaint(page.map((x) => x.i), c.i);
              list.querySelectorAll(".cp-chunk.hot").forEach(
                (r) => r.classList.remove("hot"));
              row.classList.add("hot");
            };
            list.appendChild(row);
          });
          if (page.length && reset) {
            towerPaint(page.map((x) => x.i), page[0].i);
          }
          if (!d.total) {
            list.innerHTML =
              "<span class='muted'>nothing captured here yet</span>";
          }
          more.style.display =
            (offset + 200 < d.total) ? "inline-block" : "none";
        } catch (err) { list.textContent = err.message; }
        more.disabled = false;
      }
      load(true);
    }

    /* #795: the WHOLE document, wherever it lives. */
    async function doc(file) {
      left.innerHTML = "<span class='muted'>opening " + esc(file)
        + "…</span>";
      try {
        const d = await api.get("/api/speakbox/"
          + encodeURIComponent(file) + "?mind="
          + encodeURIComponent(rid));
        left.innerHTML = "";
        const bar = document.createElement("div");
        bar.className = "cp-row";
        bar.innerHTML = "<button class='cp-up'>‹ sources</button>"
          + "<b>📄 " + esc(file) + "</b><span class='muted'>"
          + (d.mind ? "lives in " + esc(d.mind) : "") + "</span>";
        bar.querySelector(".cp-up").onclick = () => sources();
        left.appendChild(bar);
        const txt = document.createElement("div");
        txt.className = "cp-doc";
        txt.textContent = d.text || "(empty)";
        left.appendChild(txt);
      } catch (err) { left.textContent = err.message; }
    }

    sources();
    ensureGrips();
  }

  let obs = null;
  function obsStop() {
    if (!obs) return;
    cancelAnimationFrame(obs.raf || 0);
    clearInterval(obs.poll || 0);
    try { obs.renderer.dispose(); } catch { /* gone */ }
    obs = null;
  }

  /* #822: THE INFLUENCE OBSERVATORY. The active crystal's minds rise
   * as a hex city — a slowly turning, gently undulating topography —
   * and every time crystal material is staged into somebody's mouth a
   * trajectory arcs from that mind's tower to the character it is
   * seeding. Click a connection (or its console row) to read the exact
   * chunk and how it is being used. */
  async function openObservatory() {
    mode = "obs";
    towerStop();
    pop.style.overflow = "hidden";     // #810: nothing escapes the frame
    pop.innerHTML = "";
    const head = document.createElement("div");
    head.className = "cp-head";
    head.innerHTML = "<button class='cp-back'>‹ cabinet</button>"
      + "<b>🌆 the influence observatory</b>"
      + "<span class='muted cp-count'></span>"
      + "<button class='cp-x'>✕</button>";
    pop.appendChild(head);
    dragBy(head);
    head.querySelector(".cp-back").onclick = () => { obsStop(); draw(); };
    head.querySelector(".cp-x").onclick = () => {
      obsStop(); pop.style.display = "none"; mode = "cards";
    };
    const sel = document.createElement("select");
    (cache.crystals || []).forEach((c) => {
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = (c.on ? "◉ " : "○ ") + c.name;
      if (c.on) o.selected = true;
      sel.appendChild(o);
    });
    sel.title = "which crystal the city shows — choosing also puts it "
      + "ON AIR";
    sel.onchange = async () => {
      try {
        for (const c of cache.crystals) {
          await api.post("/api/crystals/" + c.id + "/toggle",
                         { on: c.id === sel.value });
        }
      } catch { /* quiet */ }
      await pull();
      obsStop();
      openObservatory();
    };
    head.insertBefore(sel, head.querySelector(".cp-x"));

    const body = document.createElement("div");
    body.className = "cp-body";
    const stage = document.createElement("div");
    stage.style.cssText = "flex:1;min-width:0;position:relative";
    const canvas = document.createElement("canvas");
    canvas.style.cssText = "width:100%;height:100%;display:block;"
      + "border-radius:8px;background:radial-gradient(ellipse at 50% "
      + "30%, #150b26, #04060d)";
    stage.appendChild(canvas);
    const side = document.createElement("div");
    side.className = "cp-left";
    side.style.cssText = "flex:0 0 230px;max-width:230px";
    body.appendChild(stage);
    body.appendChild(side);
    pop.appendChild(body);
    const consoleEl = document.createElement("div");
    consoleEl.className = "cp-obsconsole";
    pop.appendChild(consoleEl);
    ensureGrips();

    const say = (line) => {
      const row = document.createElement("div");
      row.textContent = line;
      consoleEl.appendChild(row);
      while (consoleEl.childElementCount > 40) {
        consoleEl.removeChild(consoleEl.firstChild);
      }
      consoleEl.scrollTop = consoleEl.scrollHeight;
    };

    try { await loadThree(); } catch (err) {
      stage.textContent = "the observatory could not open: " + err.message;
      return;
    }
    const T = window.THREE;
    const crystal = (cache.crystals || []).find((c) => c.id === sel.value)
      || (cache.crystals || [])[0];
    if (!crystal) { stage.textContent = "no crystals forged yet"; return; }
    head.querySelector(".cp-count").textContent =
      crystal.name + " · " + (crystal.strength || 50) + "%";

    const W = Math.max(420, stage.clientWidth || 560);
    const H = Math.max(300, stage.clientHeight || 380);
    canvas.width = W; canvas.height = H;
    const renderer = new T.WebGLRenderer({ canvas, antialias: true,
                                           alpha: true });
    renderer.setSize(W, H, false);
    const scene = new T.Scene();
    scene.fog = new T.Fog(0x04060d, 90, 320);
    const camera = new T.PerspectiveCamera(52, W / H, 0.1, 900);
    camera.position.set(0, 74, 128);
    camera.lookAt(0, 12, 0);
    scene.add(new T.AmbientLight(0xffffff, 0.5));
    const sun = new T.DirectionalLight(0xc9a0ff, 1.2);
    sun.position.set(60, 140, 60);
    scene.add(sun);
    const world = new T.Group();
    scene.add(world);
    const grid = new T.GridHelper(240, 24, 0x2a1a44, 0x140d24);
    world.add(grid);

    // the CITY: one tower per mind, height from its chunks
    const minds = (crystal.minds || []);
    const towers = new Map();
    const hexGeo = new T.CylinderGeometry(3.2, 3.2, 3.0, 6);
    minds.forEach((mid, i) => {
      const chunks = ((crystal.chunks || {})[mid]) | 0;
      const floors = Math.max(2, Math.min(26,
        Math.round(Math.log2(chunks + 2) * 3)));
      const angle = i * 2.39996;               // golden spiral city blocks
      const radius = 8 + Math.sqrt(i) * 13;
      const x = Math.cos(angle) * radius, z = Math.sin(angle) * radius;
      const tw = new T.Group();
      for (let f = 0; f < floors; f++) {
        const mat = new T.MeshStandardMaterial({
          color: 0x4b2a6e, metalness: 0.4, roughness: 0.45,
          emissive: 0x1b0b30 });
        const hex = new T.Mesh(hexGeo, mat);
        hex.position.y = 1.5 + f * 3.05;
        tw.add(hex);
      }
      tw.position.set(x, 0, z);
      tw.userData = { mind: mid, chunks, phase: Math.random() * 6.28 };
      world.add(tw);
      towers.set(mid, tw);
    });

    // the CAST: labeled pillars in a wide ring
    function label(text, color) {
      const cv = document.createElement("canvas");
      cv.width = 256; cv.height = 64;
      const g = cv.getContext("2d");
      g.font = "bold 30px system-ui";
      g.fillStyle = color;
      g.textAlign = "center";
      g.fillText(text.slice(0, 16), 128, 42);
      const tex = new T.CanvasTexture(cv);
      const sp = new T.Sprite(new T.SpriteMaterial({ map: tex,
        transparent: true }));
      sp.scale.set(30, 7.5, 1);
      return sp;
    }
    let castNames = { host: "Host", cohost: "Skip",
                      sfxguy: "The SFX Guy", caller: "the phone line" };
    const castPos = { host: [-96, 0, -34], cohost: [96, 0, -34],
                      sfxguy: [-96, 0, 58], caller: [96, 0, 58] };
    const pillars = {};
    Object.keys(castPos).forEach((who) => {
      const [x, , z] = castPos[who];
      const mat = new T.MeshStandardMaterial({ color: 0x1d3a56,
        emissive: 0x0c2033, metalness: 0.3, roughness: 0.5 });
      const pil = new T.Mesh(
        new T.CylinderGeometry(4.4, 5.2, 16, 8), mat);
      pil.position.set(x, 8, z);
      world.add(pil);
      const sp = label(castNames[who], "#9fd8ff");
      sp.position.set(x, 24, z);
      world.add(sp);
      pillars[who] = pil;
    });

    // the CONNECTIONS
    const arcs = [];
    const seen = new Set();
    const KINDS = {
      round: "seeded VERBATIM into the next round's script — the pair "
        + "must weave these exact words",
      sfxguy: "folded into one of the SFX guy's invented interjections",
      theme: "forced as tonight's subject material",
    };
    function arcTo(row, who) {
      const tw = towers.get(row.mind);
      const pil = pillars[who];
      if (!tw || !pil) return;
      const from = new T.Vector3(tw.position.x,
        tw.children.length * 3.05 + 2, tw.position.z);
      const to = new T.Vector3(pil.position.x, 18, pil.position.z);
      const mid = from.clone().add(to).multiplyScalar(0.5);
      mid.y += 36;
      const curve = new T.QuadraticBezierCurve3(from, mid, to);
      const geo = new T.TubeGeometry(curve, 32, 0.5, 6, false);
      const mat = new T.MeshBasicMaterial({ color: 0xc98fe0,
        transparent: true, opacity: 0.85 });
      const tube = new T.Mesh(geo, mat);
      tube.userData = { row, who, born: Date.now(), curve };
      world.add(tube);
      const pulse = new T.Mesh(
        new T.SphereGeometry(1.4, 8, 8),
        new T.MeshBasicMaterial({ color: 0xffffff }));
      tube.userData.pulse = pulse;
      world.add(pulse);
      arcs.push(tube);
    }
    function detail(row) {
      side.innerHTML = "";
      const b = document.createElement("b");
      b.textContent = row.crystal + " · " + row.mind;
      side.appendChild(b);
      const meta = document.createElement("div");
      meta.className = "muted";
      meta.style.fontSize = "10.5px";
      meta.textContent = (row.file || "(unnamed doc)") + " → "
        + (row.targets || []).map((t) => castNames[t] || t).join(" + ");
      side.appendChild(meta);
      const how = document.createElement("div");
      how.style.cssText = "font-size:11px;color:#9fd8b5;margin:4px 0";
      how.textContent = KINDS[row.kind] || row.kind;
      side.appendChild(how);
      const txt = document.createElement("div");
      txt.className = "cp-doc";
      txt.style.flex = "1";
      txt.textContent = row.text || "(the words were not kept)";
      side.appendChild(txt);
    }
    canvas.addEventListener("click", (ev) => {
      const r = canvas.getBoundingClientRect();
      const pt = new T.Vector2(
        ((ev.clientX - r.left) / r.width) * 2 - 1,
        -((ev.clientY - r.top) / r.height) * 2 + 1);
      const ray = new T.Raycaster();
      ray.setFromCamera(pt, camera);
      const hit = ray.intersectObjects(arcs, false)[0];
      if (hit) detail(hit.object.userData.row);
    });

    async function poll() {
      try {
        const d = await api.get("/api/crystals/influence");
        if (d.cast) castNames = Object.assign(castNames, d.cast);
        (d.rows || []).forEach((row) => {
          const key = row.ts + "|" + row.mind + "|" + row.file
            + "|" + (row.text || "").slice(0, 24);
          if (seen.has(key)) return;
          seen.add(key);
          if (row.crystal !== crystal.name) return;
          (row.targets || []).forEach((who) => arcTo(row, who));
          const when = new Date(row.ts * 1000)
            .toLocaleTimeString([], { hour12: false });
          say("[" + when + "] " + row.mind + "/" + (row.file || "?")
            + " → " + (row.targets || []).join("+") + " · "
            + (KINDS[row.kind] || row.kind) + " · “"
            + (row.text || "").slice(0, 70) + "…”");
          detail(row);
        });
      } catch { /* agent quiet */ }
    }
    obs = { renderer, raf: 0, poll: setInterval(poll, 4000) };
    say("observatory open — " + crystal.name + " at "
      + (crystal.strength || 50) + "% is seeding the cast; every arc "
      + "is material leaving the tower for somebody's mouth");
    poll();
    (function frame() {
      if (!obs) return;
      obs.raf = requestAnimationFrame(frame);
      const t = Date.now() / 1000;
      world.rotation.y = t * 0.05;                       // the slow turn
      towers.forEach((tw) => {                           // the undulation
        tw.position.y = Math.sin(t * 0.8 + tw.userData.phase) * 1.6;
      });
      const now = Date.now();
      for (let i = arcs.length - 1; i >= 0; i--) {
        const a = arcs[i];
        const age = (now - a.userData.born) / 1000;
        a.material.opacity = Math.max(0, 0.85 - age / 90);
        const at = (t * 0.35 + i * 0.17) % 1;
        a.userData.pulse.position.copy(a.userData.curve.getPoint(at));
        a.userData.pulse.material.opacity = a.material.opacity;
        if (age > 95) {
          world.remove(a); world.remove(a.userData.pulse);
          arcs.splice(i, 1);
        }
      }
      renderer.render(scene, camera);
    })();
  }

  function draw() {
    mode = "cards";
    towerStop();
    obsStop();
    pop.style.overflow = "auto";       // the card list scrolls again
    pop.innerHTML = "";
    const head = document.createElement("div");
    head.className = "cp-head";
    head.innerHTML = "<b>🔮 The crystal cabinet</b>"
      + "<span class='muted'>drag me · corner resizes</span>"
      + "<button class='cp-obs' title='the influence observatory — "
      + "watch the active crystal seed the cast (#822)'>🌆</button>"
      + "<button class='cp-x'>✕</button>";
    pop.appendChild(head);
    dragBy(head);
    head.querySelector(".cp-obs").onclick = () => openObservatory();
    head.querySelector(".cp-x").onclick = () => {
      pop.style.display = "none";
    };

    if (!cache.crystals.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No crystals forged yet — extract one from an "
        + "artist's lyrics first.";
      pop.appendChild(empty);
    }

    for (const c of cache.crystals) {
      const card = document.createElement("div");
      card.className = "cp-card" + (c.on ? " on" : "");

      const r1 = document.createElement("div");
      r1.className = "cp-row";
      r1.innerHTML = "<b class='cp-name'>" + esc(c.name) + "</b>"
        + "<span class='muted'>" + chunkSum(c).toLocaleString()
        + " chunks</span><span class='cp-spacer'></span>"
        + "<button class='cp-read' title='read this crystal — sources, "
        + "chunks, and the tower'>📜</button>"
        + "<button class='cp-on'>" + (c.on ? "ON AIR" : "off")
        + "</button><button class='cp-del' title='shatter this crystal "
        + "(the minds survive)'>💥</button>";
      r1.querySelector(".cp-read").onclick = () =>
        openMind(c.minds || [], c.name);
      r1.querySelector(".cp-on").onclick = async () => {
        try {
          await api.post("/api/crystals/" + c.id + "/toggle",
                         { on: !c.on });
        } catch { /* quiet */ }
        await pull(); paintBtn(); draw();
      };
      r1.querySelector(".cp-del").onclick = async () => {
        if (!confirm("Shatter \u201c" + c.name
                     + "\u201d? Its album-minds survive.")) return;
        try { await api.del("/api/crystals/" + c.id); } catch { }
        await pull(); paintBtn(); draw();
      };
      card.appendChild(r1);

      const r2 = document.createElement("div");
      r2.className = "cp-row";
      r2.innerHTML = "<label title='how hard the crystal presses on the "
        + "universe: the share of banter swaths and prompt flavor drawn "
        + "from its minds'>strength</label>"
        + "<input type='range' min='5' max='100' step='5' value='"
        + (c.strength || 50) + "'>"
        + "<span class='cp-pct'>" + (c.strength || 50) + "%</span>";
      const slider = r2.querySelector("input");
      slider.oninput = () => {
        r2.querySelector(".cp-pct").textContent = slider.value + "%";
      };
      slider.onchange = () =>
        save(c.id, { strength: parseInt(slider.value, 10) });
      card.appendChild(r2);

      // #814: a DRILL-DOWN TREE — every mind in view again (members
      // pinned first and highlighted), each expanding to its songs,
      // each song expanding to its lyrics, everything collapsible.
      const r3 = document.createElement("div");
      r3.className = "cp-mindtable";
      const hd = document.createElement("div");
      hd.className = "cp-mindrow cp-mindhead";
      hd.innerHTML = "<span>in</span><span>mind</span>"
        + "<span class='cp-md-n'>chunks</span><span class='cp-md-all'>"
        + "<button class='cp-exall' title='expand every mind'>⊞</button>"
        + "<button class='cp-coall' title='collapse everything'>⊟"
        + "</button></span>";
      r3.appendChild(hd);
      hd.querySelector(".cp-exall").onclick = () =>
        r3.querySelectorAll("details.cp-mindnode").forEach(
          (d) => { d.open = true; });
      hd.querySelector(".cp-coall").onclick = () =>
        r3.querySelectorAll("details").forEach(
          (d) => { d.open = false; });
      const have = new Set(c.minds || []);
      const allRows = (mindsAll.length ? mindsAll
        : (c.minds || []).map((id) => ({
            id, name: id, chunks: (c.chunks || {})[id] })))
        .slice().sort((a, b) =>
          (have.has(b.id) - have.has(a.id))
          || String(a.name || a.id).localeCompare(String(b.name || b.id)));
      const loadLyrics = async (box, rid, file) => {
        if (box.dataset.done) return;
        box.dataset.done = "1";
        box.textContent = "reading…";
        try {
          const d = await api.get("/api/speakbox/"
            + encodeURIComponent(file) + "?mind="
            + encodeURIComponent(rid));
          box.textContent = d.text || "(empty)";
        } catch (err) { box.textContent = err.message; }
      };
      const loadSongs = async (box, rid) => {
        if (box.dataset.done) return;
        box.dataset.done = "1";
        box.innerHTML = "<span class='muted'>reading the songs…</span>";
        try {
          const d = await api.get("/api/speakbox/minds/"
            + encodeURIComponent(rid) + "/sources");
          box.innerHTML = "";
          const srcs = (d.sources || []).slice().sort((x, y) =>
            String(x.file).localeCompare(String(y.file)));
          if (!srcs.length) {
            box.innerHTML = "<span class='muted'>nothing embedded in "
              + "this mind yet</span>";
          }
          srcs.forEach((s) => {
            const song = document.createElement("details");
            song.className = "cp-songnode";
            const cap = document.createElement("summary");
            cap.innerHTML = "<span class='cp-md-name'>" + esc(s.file)
              + "</span><span class='cp-md-n'>"
              + (s.chunks | 0).toLocaleString() + "</span>";
            song.appendChild(cap);
            const ly = document.createElement("div");
            ly.className = "cp-lyrics";
            song.appendChild(ly);
            song.ontoggle = () => {
              if (song.open) loadLyrics(ly, rid, s.file);
            };
            box.appendChild(song);
          });
        } catch (err) { box.textContent = err.message; }
      };
      // #817: THIS crystal's minds inline; every other registered
      // mind lives behind a collapsed branch — still fully expandable
      // (albums → songs → lyrics), never mixed into the crystal's own
      // section.
      const mindNode = (m) => {
        const node = document.createElement("details");
        node.className = "cp-mindnode";
        const cap = document.createElement("summary");
        cap.className = "cp-mindrow" + (have.has(m.id) ? " in" : "");
        cap.title = (m.blurb || m.id) + " — click to expand its songs";
        cap.innerHTML = "<input type='checkbox'"
          + (have.has(m.id) ? " checked" : "")
          + "><span class='cp-md-name'>▸ " + esc(m.name || m.id)
          + "</span><span class='cp-md-n'>"
          + (m.chunks | 0).toLocaleString()
          + "</span><button class='cp-md-read' title='read this mind "
          + "in the big reader'>📜</button>";
        const check = cap.querySelector("input");
        check.onclick = (ev) => ev.stopPropagation();
        check.onchange = (ev) => {
          const next = new Set(have);
          if (ev.target.checked) next.add(m.id);
          else next.delete(m.id);
          save(c.id, { minds: Array.from(next) });
        };
        cap.querySelector(".cp-md-read").onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          openMind([m.id], m.name || m.id);
        };
        node.appendChild(cap);
        const songs = document.createElement("div");
        songs.className = "cp-songs";
        node.appendChild(songs);
        node.ontoggle = () => { if (node.open) loadSongs(songs, m.id); };
        return node;
      };
      const members = allRows.filter((m) => have.has(m.id));
      // #823: the branch under a crystal lists ONLY this artist's own
      // albums — a Doom crystal never shows Allen Interface discs. The
      // artist is read from the crystal's name and from the member
      // minds' id stems ("alleninterface-bomb" → "alleninterface").
      const norm = (s) => String(s || "").toLowerCase()
        .replace(/[^a-z0-9]+/g, "");
      const stems = new Set();
      [norm(c.name), norm(c.id)].forEach((s) => { if (s) stems.add(s); });
      members.forEach((m) => {
        const st = norm(String(m.id).split("-")[0]);
        if (st) stems.add(st);
        const nm = norm(String(m.name || "").split("—")[0]);
        if (nm) stems.add(nm);
      });
      const sameArtist = (m) => {
        const id = norm(m.id), nm = norm(m.name);
        for (const s of stems) {
          if (s.length >= 3 && (id.indexOf(s) === 0
              || nm.indexOf(s) === 0 || s.indexOf(id) === 0)) return true;
        }
        return false;
      };
      const others = allRows.filter((m) =>
        !have.has(m.id) && sameArtist(m));
      const strangers = allRows.filter((m) =>
        !have.has(m.id) && !sameArtist(m));
      members.forEach((m) => r3.appendChild(mindNode(m)));
      if (!members.length) {
        const none = document.createElement("div");
        none.className = "cp-mindrow";
        none.style.cursor = "default";
        none.innerHTML = "<span></span><span class='muted'>no minds in "
          + "this crystal yet — open the branch below</span>"
          + "<span></span><span></span>";
        r3.appendChild(none);
      }
      if (others.length) {
        const branch = document.createElement("details");
        branch.className = "cp-addminds";
        const cap = document.createElement("summary");
        cap.textContent = "＋ more of this artist (" + others.length
          + ") — check one to add it to this crystal";
        branch.appendChild(cap);
        const box = document.createElement("div");
        box.className = "cp-mindtable";
        others.forEach((m) => box.appendChild(mindNode(m)));
        branch.appendChild(box);
        r3.appendChild(branch);
      }
      if (strangers.length) {
        // #823: different artists stay OUT of this crystal's list — one
        // collapsed line at the very bottom is the only trace, kept so
        // a mind can still be grafted across on purpose.
        const far = document.createElement("details");
        far.className = "cp-addminds cp-strangers";
        const cap2 = document.createElement("summary");
        cap2.textContent = "⚠ different artists (" + strangers.length
          + ") — not this crystal's; open only to graft one in";
        far.appendChild(cap2);
        const box2 = document.createElement("div");
        box2.className = "cp-mindtable";
        far.appendChild(box2);
        let built = false;
        far.ontoggle = () => {
          if (!far.open || built) return;
          built = true;
          strangers.forEach((m) => box2.appendChild(mindNode(m)));
        };
        r3.appendChild(far);
      }
      card.appendChild(r3);

      const r4 = document.createElement("div");
      r4.className = "cp-row";
      const tint = document.createElement("input");
      tint.type = "text";
      tint.className = "cp-tint";
      tint.placeholder = "tint — a line of flavor whispered into the "
        + "studio (optional)";
      tint.value = c.tint || "";
      tint.onchange = () => save(c.id, { tint: tint.value.slice(0, 500) });
      r4.appendChild(tint);
      card.appendChild(r4);
      pop.appendChild(card);
    }

    const jobs = Object.values(cache.extractions || {})
      .filter((j) => j.stage && j.stage !== "done");
    if (jobs.length) {
      const jd = document.createElement("div");
      jd.className = "muted";
      jd.textContent = "\u26cf forging: " + jobs.map((j) =>
        j.artist + " " + Math.round((j.progress || 0) * 100) + "%")
        .join(" \u00b7 ");
      pop.appendChild(jd);
    }
    ensureGrips();
  }

  btn.addEventListener("click", async () => {
    const open = pop.style.display !== "none";
    if (open) {
      pop.style.display = "none"; towerStop(); mode = "cards"; return;
    }
    pop.style.display = "flex";
    popRestore();
    await pull(); paintBtn(); draw();
  });
  document.addEventListener("click", (ev) => {
    // A button that a redraw consumed mid-click is not an OUTSIDE
    // click — that was the 🌆 toggle making the cabinet vanish.
    if (!ev.target.isConnected) return;
    if (pop.style.display !== "none" && !pop.contains(ev.target)
        && ev.target !== btn && !btn.contains(ev.target)) {
      pop.style.display = "none";
      towerStop();
      obsStop();
      mode = "cards";
    }
  });
  pull().then(paintBtn);
  setInterval(async () => {
    await pull(); paintBtn();
    // never repaint the viewer, or under the user's cursor mid-edit
    if (pop.style.display !== "none" && mode === "cards"
        && !(pop.contains(document.activeElement)
             && document.activeElement.tagName === "INPUT")) draw();
  }, 30000);
}
initCrystalBtn();

document.querySelectorAll(".tab").forEach((button) => {
  if (button.id === "threejsBtn" || button.id === "stationBtn"
      || button.id === "sampleTabBtn") return;
  button.addEventListener("click", () => selectView(button.dataset.view));
});

$("refreshBtn").onclick = refresh;
$("openBrowserBtn").onclick = () => api.openExternal(config.baseUrl);
// #809: F5 reloads the page, like a browser — same action as the R
// button. (Keys pressed INSIDE the webview are caught in main.js;
// this covers focus anywhere in the chrome.)
document.addEventListener("keydown", (ev) => {
  if (ev.key === "F5") {
    ev.preventDefault();
    const r = $("reloadFrameBtn");
    if (r) r.click();
  }
});

$("reloadFrameBtn").onclick = () => {
  const frame = activeFrame();
  if (frame) frame.reload();
};
$("fullscreenBtn").onclick = () => {
  document.body.classList.toggle("immersive");
};
$("panicBtn").onclick = panicRecover;
const broadcastTarget = $("broadcastTarget");
broadcastTarget.value = desiredBroadcast;
broadcastTarget.oninput = (event) => setDesiredBroadcast(event.target.value);
broadcastTarget.onchange = (event) => setBroadcastTarget(event.target.value);
$("fmSwitch").onchange = (event) => setFm(event.target.checked);
const boothMonitorToggle = $("boothMonitor");
if (boothMonitorToggle) {
  boothMonitorToggle.checked = boothMonitor;
  boothMonitorToggle.onchange = (event) => {
    boothMonitor = event.target.checked;
    localStorage.setItem("pineDesktopBoothMonitor", boothMonitor ? "1" : "0");
    // #997: the switch now governs the shell's own music player too, so
    // it has to re-gate it and not only the webviews.
    rerouteAudioNow();
  };
}
/* #904: THE ON-AIR MARQUEE — the strip across the very top of the app.
 *
 * "anytime someone's saying anything, text will be scrolling by indicating
 * who is saying it and what is being said. On the left side, I want it to
 * say what segment in the scheduler that we're on ... click on this option
 * and have a drop down that lets me choose which segment to jump to ...
 * whenever I click the text, I want it to pop up with a window illustrating
 * all the systems that contributed to making that piece of text possible in
 * the form of a 3JS simulation."
 *
 * Nothing in here is rebuilt on a timer (#883/#887). The belt only ever has
 * items APPENDED to its tail, and retires them off its head once they have
 * scrolled clean past the left edge — text on screen is never rewritten and
 * the container is never emptied. The segment sheet is fetched and built
 * only when the dropdown OPENS. The provenance window is built once per
 * click and torn down on close.
 *
 * It reads /api/dj, which the booth already serves: `chat` for the lines,
 * `speaking_now` for which of them is sounding this second,
 * `dialogue_flow.schedule.now` (#937) for the segment, and `selling_now`
 * (#900) for the piece on the block.
 */

/* three.js is VENDORED — the agent serves it at /vendor/three.min.js and
 * there is no CDN out here. Loaded once, on the first click that needs it. */
let dxThreeP = null;
function dxLoadThree() {
  if (window.THREE) return Promise.resolve();
  if (dxThreeP) return dxThreeP;
  dxThreeP = new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = ((config && config.baseUrl) || "http://127.0.0.1:8096")
      + "/vendor/three.min.js";
    tag.onload = () => resolve();
    tag.onerror = () => { dxThreeP = null; reject(new Error("no three.js")); };
    document.head.appendChild(tag);
  });
  return dxThreeP;
}

/* The systems behind ONE line, read off /api/dj/provenance (#888/#889).
 * That endpoint already gathers everything — the prompt as sent, the script
 * that came back, the model, the material about him, the speakbox swaths,
 * the vector hits, the crystal, the schedule entry, the armed system prompt,
 * the voice, and whether the audio was prepared ahead or made live. This
 * only shapes it into nodes; it invents nothing. */
function dxProvSystems(p) {
  const out = [];
  const line = p.line || {};
  const written = p.written || {};
  const render = p.render || {};
  const sched = p.schedule || {};
  const system = p.system || {};
  const add = (key, label, tone, head, rows, leaves) => {
    const kept = (rows || []).filter(Boolean).map(String);
    const kids = (leaves || []).filter(Boolean).map(String);
    if (!head && !kept.length && !kids.length) return;
    out.push({ key, label, tone, head: String(head || ""),
               rows: kept, leaves: kids });
  };

  add("model", "The language model", 0x7fd4ff, written.model || p.model || "",
      [written.temp != null ? "temperature " + written.temp : "",
       written.num_ctx ? "context window " + written.num_ctx : "",
       written.ms ? "wrote it in " + written.ms + "ms" : "",
       written.chars ? written.chars + " characters came back" : "",
       written.budget ? "budget " + written.budget : ""], []);

  /* #983: two prompts, drawn as two. The agent's armed prompt governs
     the assistant you talk to and nothing about the booth; what the
     booth follows is the station's own disposition layer. Showing the
     first one under "the booth is following it" is exactly what hid the
     coupling between them. */
  add("system", "The agent's system prompt", 0xc98fe0,
      system.name || "(none armed)",
      ["governs the assistant, not the booth",
       (system.text || "").slice(0, 220)], []);

  add("station", "The station's standing instructions", 0xe0c98f,
      system.station_followed ? "the booth is following them"
        : "the booth is not bound to any",
      [(system.station || "(none set on the radio prompt desk)")
        .slice(0, 220)], []);

  add("schedule", "The running order", 0x8fe0b0,
      sched.kind || sched.kind_now || "(no entry named this round)",
      [(sched.prompt || sched.prompt_now || "").slice(0, 220)], []);

  // The bodies of material below only earn a node when they actually put
  // something in — an empty ring of "0 documents" nodes is a picture of
  // nothing, and the point of the thing is what DID contribute.
  const docs = p.documents || [];
  if (docs.length) {
    add("speakbox", "The speakbox", 0xe0c98f, "",
        [docs.length + " document(s) reached this line"],
        docs.map((d) => (d.quoted ? "quoted: " : "")
          + (d.file || "") + " — " + (d.how || "")));
  }
  const vecs = p.vectors || [];
  if (vecs.length) {
    add("vectors", "The vector index", 0x9fb0ff, "",
        [vecs.length + " search(es) around this line"],
        vecs.map((v) => (v.file || v.query || "a search")
          + (v.score != null ? " · " + v.score : "")));
  }
  const shards = p.crystal || [];
  if (shards.length) {
    add("crystal", "The crystal", 0xf2a0d0, "",
        [shards.length + " shard(s) tinting the water"],
        shards.map((c) => (c.in_prompt ? "in the prompt: " : "")
          + (c.text || c.file || "")));
  }
  const mine = p.material || [];
  if (mine.length) {
    add("material", "His own material", 0xffd7a1, "",
        [mine.length + " line(s) about him were in the prompt"],
        mine.map((m) => (m.tally ? "a tally: " : "") + (m.text || "")));
  }
  const asks = p.requests || [];
  if (asks.length) {
    add("requests", "The request ledger", 0xd0e08f, "",
        [asks.length + " standing request(s) were in view"],
        asks.map((r) => (r.title || r.text || "a request")
          + (r.count != null ? " ×" + r.count : "")));
  }

  add("voice", "The voice", 0x65d1a0,
      (line.voice || "") + (line.engine ? " · " + line.engine : ""),
      [render.ms ? "rendered in " + render.ms + "ms" : "",
       line.seconds ? line.seconds + "s on air" : "",
       render.how || ""], []);

  add("room", "The recording room", 0xb0c4d4, p.prepared || "",
      [p.burst ? "aired in a burst of " + p.burst : "",
       line.kind ? "filed as a " + line.kind + " line" : "",
       line.aired ? "went out " + line.aired : ""], []);

  return out;
}

/* The infographic. One node per system on a ring around the LINE itself,
 * each with its own contributions orbiting it, and a beam into the middle
 * whose thickness is how much that system put in. */
function dxProvScene(canvas, systems, centreText, onPick) {
  const T = window.THREE;
  const host = canvas.parentElement;
  const W = Math.max(320, (host && host.clientWidth) || 560);
  const H = Math.max(240, (host && host.clientHeight) || 400);
  canvas.width = W;
  canvas.height = H;
  const renderer = new T.WebGLRenderer({ canvas, antialias: true,
                                         alpha: true });
  renderer.setSize(W, H, false);
  const scene = new T.Scene();
  scene.fog = new T.Fog(0x05080d, 110, 340);
  const camera = new T.PerspectiveCamera(50, W / H, 0.1, 1400);
  scene.add(new T.AmbientLight(0xffffff, 0.62));
  const sun = new T.DirectionalLight(0x9fd8ff, 1.15);
  sun.position.set(50, 110, 70);
  scene.add(sun);
  const world = new T.Group();
  scene.add(world);
  const floor = new T.GridHelper(190, 19, 0x1c2b3a, 0x111a24);
  floor.position.y = -16;
  world.add(floor);

  const sprite = (text, colour) => {
    const pad = 16;
    const c = document.createElement("canvas");
    let g = c.getContext("2d");
    const font = "600 30px Inter, Segoe UI, sans-serif";
    g.font = font;
    const w = Math.min(620, Math.ceil(g.measureText(text).width) + pad * 2);
    c.width = w;
    c.height = 46;
    g = c.getContext("2d");
    g.font = font;
    g.fillStyle = "rgba(6,10,16,.72)";
    g.fillRect(0, 0, w, 46);
    g.fillStyle = colour;
    g.textBaseline = "middle";
    g.fillText(text, pad, 24);
    const mat = new T.SpriteMaterial({ map: new T.CanvasTexture(c),
                                       transparent: true,
                                       depthWrite: false });
    const sp = new T.Sprite(mat);
    sp.scale.set(w / 22, 46 / 22, 1);
    return sp;
  };

  const beam = (from, to, thick, colour) => {
    const dir = new T.Vector3().subVectors(to, from);
    const len = dir.length() || 0.01;
    const mesh = new T.Mesh(
      new T.CylinderGeometry(thick, thick * 0.45, len, 8, 1, true),
      new T.MeshBasicMaterial({ color: colour, transparent: true,
                                opacity: 0.42 }));
    mesh.position.copy(from).add(to).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0),
                                       dir.clone().normalize());
    return mesh;
  };

  // THE LINE, in the middle. Everything else points at it.
  const heart = new T.Mesh(
    new T.IcosahedronGeometry(6.4, 1),
    new T.MeshStandardMaterial({ color: 0xffd7a1, emissive: 0x774d18,
                                 metalness: 0.35, roughness: 0.35 }));
  world.add(heart);
  const heartTag = sprite(centreText, "#ffe9c9");
  heartTag.position.set(0, 12.5, 0);
  world.add(heartTag);

  const picks = [];
  const ring = 46;
  systems.forEach((sys, i) => {
    const turn = (i / Math.max(1, systems.length)) * Math.PI * 2;
    const lift = 2 + (i % 3) * 7;
    const at = new T.Vector3(Math.cos(turn) * ring, lift,
                             Math.sin(turn) * ring);
    const weight = 1 + sys.leaves.length + sys.rows.length * 0.4;
    const size = Math.max(2.4, Math.min(6.2, 2.2 + Math.log(weight + 1) * 1.5));
    const node = new T.Mesh(
      new T.SphereGeometry(size, 22, 16),
      new T.MeshStandardMaterial({ color: sys.tone, emissive: sys.tone,
                                   emissiveIntensity: 0.16,
                                   metalness: 0.3, roughness: 0.42 }));
    node.position.copy(at);
    node.userData = { key: sys.key, label: sys.label, base: sys.tone };
    world.add(node);
    picks.push(node);
    world.add(beam(at, new T.Vector3(0, 0, 0),
                   Math.max(0.28, Math.min(1.5, 0.28 + weight * 0.09)),
                   sys.tone));
    const tag = sprite(sys.label, "#dfeaf2");
    tag.position.set(at.x, at.y + size + 4.4, at.z);
    world.add(tag);
    // Its own contributions, orbiting it — one bead per document, per
    // vector hit, per shard, per line of his material.
    const beads = sys.leaves.slice(0, 14);
    beads.forEach((_leaf, k) => {
      const spin = (k / Math.max(1, beads.length)) * Math.PI * 2;
      const rad = size + 5.5;
      const where = new T.Vector3(
        at.x + Math.cos(spin) * rad,
        at.y + Math.sin(spin * 2) * 2.6,
        at.z + Math.sin(spin) * rad);
      const bead = new T.Mesh(
        new T.SphereGeometry(0.95, 12, 10),
        new T.MeshStandardMaterial({ color: sys.tone, emissive: sys.tone,
                                     emissiveIntensity: 0.35,
                                     roughness: 0.5 }));
      bead.position.copy(where);
      world.add(bead);
      world.add(beam(where, at, 0.13, sys.tone));
    });
  });

  const state = { yaw: 0.6, pitch: 0.42, dist: 152, auto: true, raf: 0,
                  hot: null, dead: false };
  const ray = new T.Raycaster();
  const flat = new T.Vector2();

  let drag = null;
  canvas.style.touchAction = "none";
  canvas.onpointerdown = (ev) => {
    drag = { x: ev.clientX, y: ev.clientY, moved: 0 };
    state.auto = false;
    try { canvas.setPointerCapture(ev.pointerId); } catch (e) { /* old */ }
  };
  canvas.onpointermove = (ev) => {
    const box = canvas.getBoundingClientRect();
    flat.x = ((ev.clientX - box.left) / box.width) * 2 - 1;
    flat.y = -((ev.clientY - box.top) / box.height) * 2 + 1;
    if (drag) {
      const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      drag.moved += Math.abs(dx) + Math.abs(dy);
      drag.x = ev.clientX; drag.y = ev.clientY;
      state.yaw += dx * 0.008;
      state.pitch = Math.max(-0.35, Math.min(1.25, state.pitch + dy * 0.006));
    }
  };
  canvas.onpointerup = (ev) => {
    const quiet = drag && drag.moved < 5;
    drag = null;
    if (!quiet) return;
    ray.setFromCamera(flat, camera);
    const hit = ray.intersectObjects(picks, false)[0];
    if (hit && typeof onPick === "function") onPick(hit.object.userData.key);
  };
  canvas.oncontextmenu = (ev) => ev.preventDefault();
  canvas.onwheel = (ev) => {
    ev.preventDefault();
    state.auto = false;
    state.dist = Math.max(52, Math.min(420,
      state.dist * (ev.deltaY > 0 ? 1.11 : 0.9)));
  };

  (function spin() {
    if (state.dead) return;
    state.raf = requestAnimationFrame(spin);
    if (state.auto) state.yaw += 0.0035;
    heart.rotation.y += 0.006;
    heart.rotation.x += 0.002;
    // Whatever the pointer is over glows; everything else settles back.
    ray.setFromCamera(flat, camera);
    const over = ray.intersectObjects(picks, false)[0];
    const under = over ? over.object.userData.key : null;
    if (under !== state.hot) {
      state.hot = under;
      picks.forEach((m) => {
        m.material.emissiveIntensity =
          (m.userData.key === under) ? 0.75 : 0.16;
      });
      canvas.style.cursor = under ? "pointer" : "grab";
    }
    const cp = Math.cos(state.pitch) * state.dist;
    camera.position.set(Math.sin(state.yaw) * cp,
                        Math.sin(state.pitch) * state.dist + 12,
                        Math.cos(state.yaw) * cp);
    camera.lookAt(0, 4, 0);
    renderer.render(scene, camera);
  })();

  return {
    stop() {
      state.dead = true;
      try { cancelAnimationFrame(state.raf); } catch (e) { /* gone */ }
      try { renderer.dispose(); } catch (e) { /* gone */ }
    }
  };
}

/* The window itself: the line, its systems as a readable ledger, and the
 * same thing as the infographic beside it. Opened by a click, never by a
 * timer, and torn right down on close. */
let dxProvLive = null;
async function dxProvOpen(lineId, who, said) {
  const pop = $("dxProvPopup");
  if (!pop || !lineId) return;
  if (dxProvLive) { try { dxProvLive.stop(); } catch (e) { /* gone */ } }
  dxProvLive = null;
  pop.textContent = "";
  pop.style.display = "flex";

  const mk = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = String(text);
    return el;
  };

  const head = mk("div", "dxp-head");
  head.appendChild(mk("b", "", "What made this line"));
  head.appendChild(mk("span", "dxp-who", who || ""));
  const shut = mk("button", "dxp-x", "✕");
  shut.title = "Close";
  head.appendChild(shut);
  pop.appendChild(head);
  const say = mk("div", "dxp-say", said || "");
  pop.appendChild(say);
  const body = mk("div", "dxp-body");
  const stage = mk("div", "dxp-stage");
  const canvas = document.createElement("canvas");
  stage.appendChild(canvas);
  stage.appendChild(mk("div", "dxp-hint",
    "drag to turn · wheel to zoom · click a node"));
  const side = mk("div", "dxp-side");
  body.appendChild(stage);
  body.appendChild(side);
  pop.appendChild(body);

  const close = () => {
    if (dxProvLive) { try { dxProvLive.stop(); } catch (e) { /* gone */ } }
    dxProvLive = null;
    pop.style.display = "none";
    pop.textContent = "";
    // Back to the middle. A window dragged off the edge of a big screen
    // and reopened on a small one would otherwise be unreachable.
    pop.style.left = "";
    pop.style.top = "";
    pop.style.transform = "";
  };
  shut.onclick = close;

  // Drag it about by the head, like the crystal cabinet.
  let grab = null;
  head.onpointerdown = (ev) => {
    if (ev.target === shut) return;
    grab = { x: ev.clientX, y: ev.clientY,
             left: pop.offsetLeft, top: pop.offsetTop };
    pop.style.transform = "none";
    pop.style.left = grab.left + "px";
    pop.style.top = grab.top + "px";
    try { head.setPointerCapture(ev.pointerId); } catch (e) { /* old */ }
  };
  head.onpointermove = (ev) => {
    if (!grab) return;
    pop.style.left = (grab.left + ev.clientX - grab.x) + "px";
    pop.style.top = (grab.top + ev.clientY - grab.y) + "px";
  };
  head.onpointerup = () => { grab = null; };

  let prov = null;
  try {
    prov = await api.get("/api/dj/provenance/" + encodeURIComponent(lineId));
  } catch (err) {
    side.appendChild(mk("div", "dxp-none",
      "that line has scrolled out of the booth — its paperwork went with "
      + "it (" + err.message + ")"));
    return;
  }
  if (!prov || prov.ok === false) {
    side.appendChild(mk("div", "dxp-none",
      "nothing was written down for that line"));
    return;
  }
  say.textContent = String((prov.line || {}).text || said || "");
  head.querySelector(".dxp-who").textContent =
    String((prov.line || {}).name || (prov.line || {}).who || who || "");

  /* #970: A PHONE CALL IS NOT A LINE, IT IS A CONVERSATION.
   *
   * "When I click on a phone call, I want that pop up to also have a
   *  transcript of the phone call and a flow chart showing how the phone
   *  call flowed and how it terminated, illustrating how the customer's
   *  experience went with the station."
   *
   * The provenance graph answers "what made this ONE line", which is the
   * right answer for a line of banter and the wrong one for a hang-up
   * notice — the thing behind that row is a whole call. When the row is
   * part of a call, the call goes at the TOP of the side panel: the
   * verdict on how it went, the flow chart, the transcript, and the
   * prompts underneath it. */
  try {
    const kind = String((prov.line || {}).kind || "");
    if (kind === "hangup" || kind === "call" || kind === "drop"
        || String((prov.line || {}).who || "") === "caller") {
      await dxCallPanel(side, lineId);
    }
  } catch (e) { /* the provenance below still draws */ }

  const systems = dxProvSystems(prov);
  const cards = {};
  systems.forEach((sys) => {
    const card = mk("div", "dxp-sys");
    const h = mk("h5", "");
    const dot = mk("span", "", "●");
    dot.style.color = "#" + sys.tone.toString(16).padStart(6, "0");
    h.appendChild(dot);
    h.appendChild(mk("span", "", sys.label));
    if (sys.leaves.length) h.appendChild(mk("s", "", sys.leaves.length));
    card.appendChild(h);
    if (sys.head) card.appendChild(mk("p", "", sys.head));
    sys.rows.forEach((row) => card.appendChild(mk("p", "", row)));
    sys.leaves.slice(0, 14).forEach((leaf) =>
      card.appendChild(mk("div", "dxp-leaf", leaf)));
    side.appendChild(card);
    cards[sys.key] = card;
  });
  if (!systems.length) {
    side.appendChild(mk("div", "dxp-none",
      "this line predates the provenance ledger"));
  }

  const highlight = (key) => {
    Object.keys(cards).forEach((k) => cards[k].classList.toggle("hot",
      k === key));
    const card = cards[key];
    if (card && card.scrollIntoView) {
      card.scrollIntoView({ block: "nearest" });
    }
  };

  try {
    await dxLoadThree();
  } catch (err) {
    stage.appendChild(mk("div", "dxp-none",
      "the infographic could not be drawn: " + err.message
      + " — is the agent reachable? It serves three.js at "
      + "/vendor/three.min.js."));
    return;
  }
  try {
    dxProvLive = dxProvScene(
      canvas, systems,
      String((prov.line || {}).name || (prov.line || {}).who || "this line"),
      highlight);
  } catch (err) {
    stage.appendChild(mk("div", "dxp-none",
      "the infographic could not be drawn: " + err.message));
  }
}

function initAirMarquee() {
  const bar = $("dxMarquee");
  const lane = $("dxTicker");
  const track = $("dxTickerTrack");
  const idle = $("dxIdle");
  const segBtn = $("dxSegBtn");
  const segName = $("dxSegName");
  const segKind = $("dxSegKind");
  const segMenu = $("dxSegMenu");
  const sell = $("dxSelling");
  const sellArt = $("dxSellingArt");
  const sellName = $("dxSellingName");
  const sellWhy = $("dxSellingWhy");
  if (!bar || !lane || !track || !segBtn || !segMenu) return;

  const SPEED = 52;             // pixels a second — readable, not frantic
  const KEEP = 60;              // lines kept for the loop
  const pool = [];              // {id, name, text}
  let seen = new Set();
  let feedAt = 0;
  let offset = 0;               // where the belt has slid to
  let beltW = 0;                // total width of what is ON the belt
  let paused = false;
  let last = 0;
  let liveId = "";
  let looped = false;           // #967: the belt is showing reruns
  let segWas = "";
  let slidTo = "";
  let sellArtNow = "";

  /* #883: never rewrite a node that already says the right thing. */
  const put = (node, text) => {
    const s = (text === undefined || text === null) ? "" : String(text);
    if (node && node.textContent !== s) node.textContent = s;
  };

  /* #967: what sort of thing is going past. "I want to see any
   * references that we do when we are running ads, sound effects,
   * whenever the sound effects guy's talking, anything that's
   * happening." The booth already labels its rows; the belt threw the
   * label away. */
  const DX_KIND = {
    ad: "📣", sfx: "🔊", call: "☎", caller: "☎", news: "📰",
    manager: "📻", gallery: "🖼", station_id: "📢", track_talk: "💿",
    recap: "🔁", sting: "🔊", song: "🎵", image: "🖼",
  };

  function addToBelt(item) {
    const el = document.createElement("span");
    el.className = "dx-item";
    el.dataset.lineId = item.id;
    el.dataset.say = item.text;
    el.dataset.name = item.name;
    el.dataset.who = item.who || "";
    el.dataset.kind = item.kind || "";
    el.dataset.at = String(item.at || 0);
    const glyph = DX_KIND[String(item.kind || "").toLowerCase()];
    if (glyph) {
      const tag = document.createElement("em");
      tag.textContent = glyph;
      tag.title = String(item.kind || "");
      el.appendChild(tag);
    }
    const who = document.createElement("b");
    who.textContent = item.name;
    const what = document.createElement("i");
    what.textContent = item.text;
    el.appendChild(who);
    el.appendChild(what);
    track.appendChild(el);
    // ONE forced layout per item as it joins, and none per frame after.
    el.dataset.w = String(el.offsetWidth);
    beltW += el.offsetWidth;
    if (item.id && item.id === liveId) el.classList.add("live");
  }

  /* Keep enough on the belt to cover the lane twice over. When the newest
   * lines run out it loops the last dozen, so the marquee never sits still
   * while the booth is between rounds. */
  function fill() {
    let guard = 0;
    while (pool.length && guard < 12) {
      guard += 1;
      if (offset + beltW > lane.clientWidth * 1.8) break;
      if (feedAt >= pool.length) {
        feedAt = Math.max(0, pool.length - 12);
        looped = true;          // #967: from here on it is a rerun
      }
      addToBelt(pool[feedAt]);
      feedAt += 1;
    }
  }

  function step(now) {
    requestAnimationFrame(step);
    // Clamped at both ends: a long stall (the window was hidden) must not
    // teleport the belt, and a clock that ever went backwards must not
    // wind it the wrong way.
    const dt = last ? Math.max(0, Math.min(0.12, (now - last) / 1000)) : 0;
    last = now;
    fill();
    if (!paused) offset -= SPEED * dt;
    // Retire the head once it is clean past the left edge. Nothing on
    // screen is ever touched — only what has already gone.
    let head = track.firstElementChild;
    while (head && offset + Number(head.dataset.w || 0) <= 0) {
      offset += Number(head.dataset.w || 0);
      beltW -= Number(head.dataset.w || 0);
      track.removeChild(head);
      head = track.firstElementChild;
    }
    if (!track.firstElementChild) {
      offset = lane.clientWidth;
      beltW = 0;
    }
    // Held on hover, so the same value is not written over and over.
    const slid = "translateX(" + offset.toFixed(1) + "px)";
    if (slid !== slidTo) {
      slidTo = slid;
      track.style.transform = slid;
    }
    if (idle) {
      const want = track.firstElementChild ? "none" : "";
      if (idle.style.display !== want) idle.style.display = want;
    }
  }

  function markLive(id) {
    if (id === liveId) return;
    liveId = id;
    let on_belt = false;
    const kids = track.children;
    for (let i = 0; i < kids.length; i += 1) {
      const on = Boolean(id) && kids[i].dataset.lineId === id;
      if (on) on_belt = true;
      if (kids[i].classList.contains("live") !== on) {
        kids[i].classList.toggle("live", on);
      }
    }
    /* #967: AND THE BELT GOES AND GETS IT.
     *
     * "Make sure the marquee is scrolling, showing the message that's
     *  being said as it's being said ... I need whatever is being said
     *  to be what is scrolling by, so I can see it in real time."
     *
     * The belt only ever fed forward from wherever it had got to, and
     * looped the last dozen lines when it ran out — so what was
     * scrolling past was usually a rerun of the last minute while
     * something else entirely was going out. When a new line starts, if
     * it is not already on the belt, the feed is re-seated onto it and
     * anything looped is dropped, so the next thing to slide in is the
     * line actually being said. Lines that ARE on the belt are left
     * alone: no jump, no flicker, and nothing on screen is rewritten. */
    if (!id || on_belt) return;
    let at = -1;
    for (let i = pool.length - 1; i >= 0; i -= 1) {
      if (pool[i].id === id) { at = i; break; }
    }
    if (at < 0) return;                 // not in the pool yet; next pull
    feedAt = at;
    if (looped) {
      // Everything on the belt is a rerun. Clear it and come in fresh.
      track.textContent = "";
      offset = lane.clientWidth;
      beltW = 0;
      looped = false;
    }
    fill();
  }

  function paintSegment(state) {
    const now = ((state.dialogue_flow || {}).schedule || {}).now || {};
    const label = String(now.label || "");
    put(segName, label || "no schedule running");
    put(segKind, now.kind || "—");
    const through = Math.max(0, Math.min(1, Number(now.through) || 0));
    const pct = (through * 100).toFixed(1) + "%";
    if (segWas !== pct) {
      segWas = pct;
      segBtn.style.setProperty("--dx-through", pct);
    }
    segBtn.title = label
      ? label + " — " + Math.round(Number(now.through_seconds) || 0) + "s of "
        + Math.round(Number(now.owns_seconds) || 0) + "s. Click to jump to "
        + "another segment, or interject one for a single round."
      : "No running order is driving the show. Click to interject a "
        + "segment anyway.";
  }

  /* #900: the piece being sold, held up on the right. `src` is only ever
   * written when the FILE changes — re-setting it every poll would refetch
   * the picture and flicker it. */
  function paintSelling(state) {
    if (!sell || !sellArt) return;
    const it = state.selling_now || null;
    if (!it || !it.image) {
      if (sell.style.display !== "none") sell.style.display = "none";
      sell.classList.remove("big");
      sellArtNow = "";
      return;
    }
    if (sell.style.display !== "flex") sell.style.display = "flex";
    const name = String(it.image || "");
    // The agent's address is part of the key: this can run before boot()
    // has read the config, and a src built on an empty base would then be
    // cached as "already correct" and never fixed.
    const base = (config && config.baseUrl) || "";
    const key = base + "|" + name;
    if (base && key !== sellArtNow) {
      sellArtNow = key;
      sellArt.src = base + "/api/generations/image/"
        + encodeURIComponent(name);
    }
    put(sellName, it.title || name);
    put(sellWhy, (it.price ? "$" + it.price + " · " : "") + (it.why || ""));
    sell.title = "Selling now: " + (it.title || name)
      + (it.price ? " — " + it.price + " dollars" : "")
      + " (" + (it.why || "") + "). Click to hold it up big.";
  }

  async function pull() {
    let state = null;
    try {
      state = await api.get("/api/dj");
    } catch (err) {
      return;                   // the agent is quiet; the belt keeps rolling
    }
    if (!state) return;
    try {
      (state.chat || []).forEach((row) => {
        const id = String(row.id || "");
        const text = String(row.text || "").trim();
        if (!id || !text || seen.has(id)) return;
        seen.add(id);
        /* #967/#969: the row is kept WHOLE now, near enough. It used to
         * be reduced to {id, name, text} and everything else thrown
         * away — which is why a line on the belt could not be played
         * back, could not be downloaded, and could not say what kind of
         * thing it was. `at` is what /api/booth/clip cuts against and
         * `who` is the seat /api/dj/announce speaks in; neither can be
         * recovered from the belt afterwards. */
        pool.push({ id,
                    name: String(row.name || row.who || "the booth"),
                    text,
                    who: String(row.who || ""),
                    kind: String(row.kind || ""),
                    at: Number(row.air_at || row.ts || 0) });
      });
      if (pool.length > KEEP) {
        const cut = pool.length - KEEP;
        pool.splice(0, cut);
        feedAt = Math.max(0, feedAt - cut);
      }
      if (seen.size > 600) {
        // Re-seed rather than grow for ever; anything still in the pool
        // stays known, so nothing already shown can come round twice.
        seen = new Set(pool.map((x) => x.id));
      }
      markLive(String((state.speaking_now || {}).id || ""));
      paintSegment(state);
      paintSelling(state);
    } catch (err) { /* a bad frame never stops the marquee */ }
  }

  /* The sheet, dropped open. Fetched HERE — when it opens — so nothing is
   * ever rebuilt under a finger that is reading it (#883/#887). */
  async function openMenu() {
    segMenu.textContent = "";
    segMenu.style.display = "block";
    segBtn.classList.add("open");
    const mk = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text != null) el.textContent = String(text);
      return el;
    };
    const note = mk("div", "dx-segnote", "reading the running order…");
    segMenu.appendChild(note);
    let sheet = null;
    try {
      sheet = await api.get("/api/dj/segments");
    } catch (err) {
      note.className = "dx-segnote bad";
      note.textContent = "the running order is unreachable: " + err.message;
      return;
    }
    segMenu.textContent = "";
    const send = async (body, label) => {
      const said = mk("div", "dx-segnote", "putting " + label + " on air…");
      segMenu.appendChild(said);
      try {
        const got = await api.post("/api/dj/segments/interject", body);
        if (got && got.ok) {
          said.textContent = label + " goes out next — then the hour picks "
            + "up exactly where it left off.";
          setTimeout(() => { closeMenu(); }, 1400);
        } else {
          said.className = "dx-segnote bad";
          said.textContent = (got && got.why) || "that segment was refused";
        }
      } catch (err) {
        said.className = "dx-segnote bad";
        said.textContent = "the booth refused it: " + err.message;
      }
    };
    const slots = (sheet && sheet.slots) || [];
    if (slots.length) {
      segMenu.appendChild(mk("h4", "",
        "the hour — " + String((sheet && sheet.preset) || "")
        + (sheet && sheet.enabled === false ? " (schedule off)" : "")));
      slots.forEach((slot) => {
        const row = mk("div", "dx-segrow" + (slot.now ? " now" : ""));
        row.appendChild(mk("span", "", (slot.index + 1) + ". " + slot.label));
        row.appendChild(mk("s", "", slot.kind));
        row.appendChild(mk("u", "", slot.now ? "on air" : slot.minutes + "m"));
        row.title = "Run " + slot.label + " now — one round, then back to "
          + "the running order";
        row.onclick = () => send({ slot_id: slot.id, kind: slot.kind },
                                 slot.label);
        segMenu.appendChild(row);
      });
    }
    const kinds = (sheet && sheet.kinds) || [];
    if (kinds.length) {
      segMenu.appendChild(mk("h4", "", "or interject any segment the "
        + "station knows"));
      kinds.forEach((k) => {
        const row = mk("div", "dx-segrow");
        row.appendChild(mk("span", "", k.label));
        row.appendChild(mk("s", "", k.kind));
        row.appendChild(mk("u", "", ""));
        row.title = k.blurb || "";
        row.onclick = () => send({ kind: k.kind }, k.label);
        segMenu.appendChild(row);
      });
    }
    segMenu.appendChild(mk("div", "dx-segfoot",
      "An interjection is ONE round. It goes out ahead of whatever the "
      + "clock had lined up, and the hour then carries on from exactly "
      + "where it was — nothing on the sheet moves."));
  }

  function closeMenu() {
    segMenu.style.display = "none";
    segBtn.classList.remove("open");
  }

  segBtn.onclick = (ev) => {
    ev.stopPropagation();
    if (segMenu.style.display === "block") closeMenu();
    else openMenu();
  };
  document.addEventListener("click", (ev) => {
    if (segMenu.style.display !== "block") return;
    if (segMenu.contains(ev.target) || segBtn.contains(ev.target)) return;
    closeMenu();
  });

  // Reading a line means stopping it: the belt holds while the pointer is
  // over it, which is also what makes a moving line clickable.
  /* #968: the booth window, toggled from up here. It lives inside the
   * control panel's own page, so the door is opened by running the
   * panel's own function in that frame — nothing is duplicated. */
  const boothBtn = $("dxBoothBtn");
  if (boothBtn) {
    boothBtn.onclick = async () => {
      const frame = $("controlFrame");
      if (!frame || !frame.src || typeof frame.executeJavaScript !== "function") {
        noteRouteError("the control panel is not loaded yet");
        return;
      }
      try {
        const on = await frame.executeJavaScript(
          "(function(){try{"
          + "var p=document.getElementById('djTalkPopup');"
          + "if(p){djTalkClose(true);return false;}"
          + "djBoothReopen();return true;"
          + "}catch(e){return null;}})()");
        boothBtn.classList.toggle("on", on === true);
      } catch (e) {
        noteRouteError("the booth could not be reached");
      }
    };
  }

  lane.addEventListener("mouseenter", () => { paused = true; });
  lane.addEventListener("mouseleave", () => { paused = false; });
  /* #969: RIGHT-CLICK ANY LINE GOING PAST.
   *
   * "I want to be able to right click any option in the marquee and have
   *  a drop down menu that offers options for viewing the transcript,
   *  which shows the transcript in a pop-up, or to download the MP3 of
   *  that moment in time at which that clip was said. Also offer an
   *  option for play where basically the moment is cued for play again."
   *
   * Left click already opens the provenance graph, so the three actions
   * asked for go on the right button. Everything they need is on the
   * item since #967 — the id the server cuts audio against, the air time
   * that names the moment, the seat to speak it back in, and the words. */
  track.addEventListener("contextmenu", (ev) => {
    let el = ev.target;
    while (el && el !== track && !el.dataset.lineId) el = el.parentElement;
    if (!el || el === track || !el.dataset.lineId) return;
    ev.preventDefault();
    dxLineMenu(ev, {
      id: el.dataset.lineId,
      say: el.dataset.say || "",
      name: el.dataset.name || "",
      who: el.dataset.who || "",
      kind: el.dataset.kind || "",
      at: Number(el.dataset.at || 0),
    });
  });
  track.addEventListener("click", (ev) => {
    let el = ev.target;
    while (el && el !== track && !el.dataset.lineId) el = el.parentElement;
    if (!el || el === track || !el.dataset.lineId) return;
    dxProvOpen(el.dataset.lineId, el.dataset.name, el.dataset.say);
  });
  if (sell) {
    sell.onclick = () => { sell.classList.toggle("big"); };
  }

  offset = lane.clientWidth;
  requestAnimationFrame(step);
  pull();
  setInterval(pull, 2500);
}
initAirMarquee();

$("launchBtn").onclick = async () => { await saveConfig({ mode: "launch" }); await api.startBackend(); await refresh(); };
$("attachBtn").onclick = async () => { await saveConfig({ mode: "attach" }); await refresh(); };
$("stopBtn").onclick = async () => { await api.stopBackend(); await refresh(); };
$("setupBtn").onclick = async () => { selectView("logs"); await api.setupBackend(); };
$("saveSettingsBtn").onclick = () => saveConfig();
$("modeLaunch").onclick = () => saveConfig({ mode: "launch" });
$("modeAttach").onclick = () => saveConfig({ mode: "attach" });

$("probeBtn").onclick = async () => { await api.post("/api/pinebox/probe", {}); await refresh(); };
$("initBtn").onclick = async () => { await api.post("/api/pinebox/initialize", { speak: true }); await refresh(); };
$("recoverBtn").onclick = async () => { await api.post("/api/pinebox/recover", { restart: true }); await refresh(); };
$("listenBtn").onclick = async () => {
  const result = await api.post("/api/pinebox/listen", { prompt: $("sayText").value.trim() });
  $("sayResult").textContent = result.message || result.status || "listening";
};
$("sayBtn").onclick = async () => {
  const text = $("sayText").value.trim();
  if (!text) return;
  const result = await api.post("/api/say", { text });
  $("sayResult").textContent = result.answer || result.status || "sent";
};
$("startRadioBtn").onclick = async () => { await api.post("/api/dj/start", {}); await refresh(); };
$("stopRadioBtn").onclick = async () => { await api.post("/api/dj/stop", {}); await refresh(); };
$("nextRadioBtn").onclick = async () => { await api.post("/api/dj/next", {}); await refresh(); };

document.querySelectorAll("[data-route]").forEach((button) => {
  button.addEventListener("click", () => api.openExternal(viewUrl(button.dataset.route)));
});

document.querySelectorAll("[data-view-target]").forEach((button) => {
  button.addEventListener("click", () => selectView(button.dataset.viewTarget));
});

api.onBackendLog(appendLog);
if (typeof api.onSupportProgress === "function") {
  api.onSupportProgress(updateRebuildProgress);
}

(async function boot() {
  initRailResizer();
  initAppVolume();
  await loadConfig();
  (await api.backendLog()).forEach(appendLog);
  if (config.mode === "launch") {
    try { await api.startBackend(); } catch (err) { appendLog(`[desktop] ${err.message}\n`); }
  }
  await waitForAgent(15000);
  await applyDefaultBroadcast();
  await refresh();
  await pollDesktopRadio();
  setInterval(refresh, 6000);
  setInterval(pollDesktopRadio, 1500);
  // #802: the first real click is the autoplay permission — use it.
  document.addEventListener("click", () => {
    if (!pendingPlayGesture) return;
    const player = $("desktopRadioPlayer");
    if (player && player.paused) {
      player.play().then(() => { pendingPlayGesture = false; })
        .catch(() => {});
    }
  }, true);
})();
