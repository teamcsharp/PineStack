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

const ROUTES = {
  box: { label: "Pine Box", music: "box", voice: "box", reply: "box", voice_device: "pine", box_talk: true },
  // #814: web/app route audio to the PAGE — they must not silently
  // re-point the core DEVICE at the retired pine satellite. They
  // leave voice_device alone; only box/nabu name a device.
  web: { label: "Web page", music: "here", voice: "here", reply: "here", box_talk: false },
  app: { label: "Application", music: "off", voice: "here", reply: "here", box_talk: false },
  // #786: Nabu is the CORE broadcast device — broadcasting to it means the
  // WHOLE station: music and the DJ voice both. music "off" here was why
  // the speaker sat silent between rounds.
  nabu: { label: "Nabu", music: "box", voice: "box", reply: "box", voice_device: "nabu", box_talk: true }
};

const EMBEDDED_ROUTES = {
  box: { djOutput: "box", djVoiceOut: "box", djReplyOut: "box" },
  web: { djOutput: "here", djVoiceOut: "here", djReplyOut: "here" },
  app: { djOutput: "off", djVoiceOut: "here", djReplyOut: "here" },
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

function setAppVolume(value, persist = true) {
  const raw = Number(value);
  appVolume = Math.max(0, Math.min(1, Number.isFinite(raw) ? raw : 0.35));
  const player = $("desktopRadioPlayer");
  if (player) {
    player.volume = appVolume;
    player.muted = appVolume <= 0;
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
    const volume = ${JSON.stringify(appVolume)};
    const audible = ${JSON.stringify(audible)};
    window.__pineDesktopVolume = audible ? volume : 0;
    window.__pineDesktopAudible = audible;
    const apply = () => {
      try {
        localStorage.setItem("pineMusicVolume", String(audible ? volume : 0));
        localStorage.setItem("pineMusicMuted", audible && volume > 0 ? "0" : "1");
      } catch (error) {}
      document.querySelectorAll("audio,video").forEach((node) => {
        // #789: the booth-monitor switch governs LIVE broadcast audio only
        // (elements tagged data-pine-live: the music player + booth voice
        // lines). Tapes from the cache and anything you deliberately press
        // play on stay audible at app volume, always.
        const live = !!(node.dataset && node.dataset.pineLive);
        const nodeAudible = live ? audible : true;
        const nextVolume = nodeAudible ? volume : 0;
        if (Math.abs(node.volume - nextVolume) > 0.001) node.volume = nextVolume;
        const muted = !nodeAudible || volume <= 0;
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
    return volume;
  })();`;
}

function audibleFrame() {
  if (!boothMonitor) return null;
  return activeFrame() || ($("controlFrame")?.src ? $("controlFrame") : null)
    || ($("radioFrame")?.src ? $("radioFrame") : null);
}

function applyAppVolumeToFrame(frame, audible = frame === audibleFrame()) {
  if (!frame || !frame.src || typeof frame.executeJavaScript !== "function") return;
  try {
    // #789: never hard-mute the whole webview for the monitor switch — that
    // silenced tape playback too. Only a zero app volume mutes everything.
    if (typeof frame.setAudioMuted === "function") frame.setAudioMuted(appVolume <= 0);
    frame.executeJavaScript(appVolumeScript(audible)).catch(() => {});
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
      if (Math.abs(player.volume - appVolume) > 0.01) {
        setAppVolume(player.volume);
      }
      if (player.muted && appVolume > 0) player.muted = false;
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
  const music = routing.music_to === "here" || (
    routing.music_to === "off" && (desiredBroadcast === "nabu" || desiredBroadcast === "app")
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

function desktopPlayerEnabled() {
  return desiredBroadcast === "nabu" || desiredBroadcast === "app";
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
  player.volume = appVolume;
  player.muted = appVolume <= 0;
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
  $("pubCopy").addEventListener("click", () => {
    const v = $("pubLink").value;
    if (v) navigator.clipboard.writeText(v).then(
      () => setText("pubStatus", "link copied — paste it anywhere"),
      () => {});
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
  }

  function stage(flow, title, num, note, cls, frac) {
    const box = mk("div", "wk-stage" + (cls ? " " + cls : ""));
    if (num != null) box.appendChild(mk("span", "wk-num", String(num)));
    box.appendChild(mk("b", "", title));
    if (note) box.appendChild(mk("div", "wk-note", note));
    if (frac != null) {
      const bar = mk("div", "wk-bar");
      const fill = mk("div", "wk-fill"
        + (frac >= 0.999 ? " good" : frac < 0.34 ? " warn" : ""));
      fill.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%";
      bar.appendChild(fill);
      box.appendChild(bar);
    }
    flow.appendChild(box);
    return box;
  }

  function paint(body, dj, pend) {
    body.textContent = "";
    const f = (dj && dj.dialogue_flow) || {};
    const rows = (pend && pend.pending) || [];
    const rendering = rows.filter((r) => r.state === "rendering");
    const ready = rows.filter((r) => r.state === "ready");
    const act = (dj && dj.activity) || {};

    const flow = mk("div", "wk-flow");

    // 1 — the writing desk
    stage(flow, "① the writing desk",
      (dj && dj.model) || "?",
      f.writing ? "writing a round now"
                : "idle — the reserve is at its target",
      f.writing ? "on" : "");
    flow.appendChild(mk("div", "wk-arrow", "▼"));

    // 2 — the reserve of written scripts
    const target = Number(f.target || 6);
    const have = Number(f.ready || 0);
    stage(flow, "② the reserve — written scripts",
      have + " / " + target,
      rows.length
        ? rows.length + " round(s) banked and waiting for a slot"
        : "nothing banked — the desk is behind",
      have >= target ? "on" : have === 0 ? "warn" : "",
      target ? have / target : 0);
    flow.appendChild(mk("div", "wk-arrow", "▼"));

    // 3 — the recording room
    const cur = rendering[0] || null;
    stage(flow, "③ the recording room",
      cur ? (cur.made + " / " + cur.chunks) : (f.window ? "open" : "waiting"),
      f.window
        ? ("building through " + f.window
           + (cur ? " — recording a round's lines" : ""))
        : "the engine is busy with the live round — building is paused",
      cur ? "on" : f.window ? "" : "warn",
      cur && cur.chunks ? cur.made / cur.chunks : null);
    flow.appendChild(mk("div", "wk-arrow", "▼"));

    // 4 — the pantry
    const secs = Number(f.buffered_seconds || pend.buffered_seconds || 0);
    stage(flow, "④ the pantry — finished audio",
      mins(secs),
      (f.pantry_clips || pend.pantry_clips || 0) + " takes on the shelf"
      + (f.pantry_mb != null
         ? " · " + f.pantry_mb + " MB of " + f.pantry_cap_mb + " MB allowed"
         : "")
      + (ready.length ? " · " + ready.length + " round(s) ready to air" : ""),
      secs > 90 ? "on" : secs < 20 ? "warn" : "",
      Math.min(1, secs / 180));
    flow.appendChild(mk("div", "wk-arrow", "▼"));

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
    stage(flow, "⑤ on air",
      dj && dj.speaking ? "talking" : "record",
      saying
        ? saying.slice(0, 160)
        : ((now.artist || "") + " — " + (now.title || "")).slice(0, 120),
      dj && dj.speaking ? "on" : "");
    body.appendChild(flow);

    // the cast
    const cast = mk("div", "wk-block");
    cast.appendChild(mk("b", "", "THE CAST"));
    const cg = mk("dl", "wk-grid");
    const names = (dj && dj.dj_names) || {};
    Object.keys(names).forEach((k) => {
      cg.appendChild(mk("dt", "", k));
      cg.appendChild(mk("dd", "", String(names[k])));
    });
    if (act.stage) {
      cg.appendChild(mk("dt", "", "doing now"));
      cg.appendChild(mk("dd", "", act.stage + " · " + (act.detail || "")));
    }
    cast.appendChild(cg);
    body.appendChild(cast);

    // the scheduler
    const q = f.quota || {};
    if (q.manager || q.caller) {
      const sch = mk("div", "wk-block");
      sch.appendChild(mk("b", "", "THE SCHEDULER — what the hour owes"));
      const sg = mk("dl", "wk-grid");
      ["manager", "caller"].forEach((k) => {
        const r = q[k];
        if (!r) return;
        sg.appendChild(mk("dt", "", k));
        sg.appendChild(mk("dd", "",
          r.aired + " of " + r.target + " this hour"
          + (r.behind ? " — behind" : " — on pace")
          + (r.due ? ", due now" : "")));
      });
      sch.appendChild(sg);
      body.appendChild(sch);
    }

    // what is stopping it
    const stops = mk("div", "wk-block");
    stops.appendChild(mk("b", "", "WHAT IS HOLDING IT UP"));
    const list = (f.blockers || []);
    if (!list.length) {
      stops.appendChild(mk("div", "wk-note", "nothing — the line is clear"));
    } else {
      list.forEach((b) => {
        const healthy = /healthy/i.test(b);
        stops.appendChild(mk("div", healthy ? "wk-note" : "wk-note wk-stop",
                             (healthy ? "✓ " : "• ") + b));
      });
    }
    body.appendChild(stops);
  }

  async function load(body) {
    try {
      const [dj, pend] = await Promise.all([
        api.get("/api/dj"),
        api.get("/api/dj/pending"),
      ]);
      paint(body, dj, pend);
    } catch (e) {
      body.textContent = "";
      body.appendChild(mk("div", "wk-note", "the works are unreachable"));
    }
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
    const x = mk("button", "wk-x", "✕");
    x.onclick = close;
    head.appendChild(x);
    pop.appendChild(head);
    pop.appendChild(mk("div", "wk-sub",
      "Every round is written, banked, recorded and stacked before it "
      + "goes out. This is where each one is right now."));
    const body = mk("div", "wk-flow-wrap");
    pop.appendChild(body);
    document.body.appendChild(pop);
    load(body);
    poll = setInterval(() => load(body), 2500);
  }

  cell.addEventListener("click", open);
}
try { initWorksPopup(); } catch (e) { /* the desk still works without it */ }

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
          try { await navigator.clipboard.writeText(link); } catch {}
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
    applyAppVolume();
  };
}
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
