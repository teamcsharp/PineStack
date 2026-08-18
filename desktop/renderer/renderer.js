const api = window.pineDesktop;

let config = null;
let currentView = "control";
let railResize = null;
let defaultBroadcastApplied = false;
let appVolume = 0.35;
let desiredBroadcast = "nabu";
let broadcastChanging = false;
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
    player.play().catch(() => noteRouteError("Click FM or the player once to allow app audio"));
    return;
  }
  if (player.paused && !player.ended) player.play().catch(() => {});
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
    const tasks = $("boxTasks");
    if (tasks) {
      tasks.textContent =
        "⚙ " + pulse.running + " running · ⏳ "
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

/* #799: the status bar — the machine's own ticker tape. Left: the newest
 * line of EVERYTHING the server is doing (pipeline feed + every shell
 * command the agent runs), click for the live 8-line terminal with
 * click-to-expand detail. Right: the go-live switch and a marquee of the
 * Spark's vitals and heaviest tenants. */
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
    if (open && stickBottom) {
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
  let scroller = null, stickBottom = true, frozenAt = 0;

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

/* #800: the sample extractor — paste a link (Ctrl+V over the 🎬 works),
 * hear the clip, set IN/OUT ranges off the playhead, stack as many ranges
 * as wanted, extract them all at once into the DJs' rotation. */
function initSamplePopup() {
  const btn = $("sampleBtn");
  const pop = $("samplePopup");
  if (!btn || !pop) return;
  let job = "", audioUrl = "", dur = 0, ranges = [], hoverBtn = false;

  const fmt = (s) => Math.floor(s / 60) + ":" +
    String(Math.floor(s % 60)).padStart(2, "0");

  function draw(stage, note) {
    pop.innerHTML = "<b>🎬 Add a sample</b>";
    const urlRow = document.createElement("div");
    urlRow.className = "sp-row";
    urlRow.innerHTML = "<input type='text' id='spUrl' placeholder='paste a "
      + "YouTube / any video link…'><button id='spFetch'>Fetch</button>"
      + "<button id='spClose'>✕</button>";
    pop.appendChild(urlRow);
    if (note) {
      const st = document.createElement("div");
      st.className = "muted";
      st.textContent = note;
      pop.appendChild(st);
    }
    if (stage === "ready") {
      const player = document.createElement("audio");
      player.controls = true;
      player.src = audioUrl;
      player.addEventListener("loadedmetadata", () => {
        dur = player.duration || 0; paint();
      });
      pop.appendChild(player);
      const bar = document.createElement("div");
      bar.className = "sp-bar";
      bar.onclick = (ev) => {
        const r = bar.getBoundingClientRect();
        player.currentTime = dur * (ev.clientX - r.left) / r.width;
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
          + fmt(r.b) + " <input type='text' placeholder='name it…' "
          + "data-n='" + n + "' value='" + (r.name || "") + "'>"
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
      player.addEventListener("timeupdate", () => {
        if (stopAt && player.currentTime >= stopAt) {
          player.pause(); stopAt = 0;
        }
      });
      $("spIn").onclick = () => { a = player.currentTime; paint(); };
      $("spOut").onclick = () => { b = player.currentTime; paint(); };
      $("spPrev").onclick = () => {
        if (b > a) { player.currentTime = a; stopAt = b; player.play(); }
      };
      $("spAdd").onclick = () => {
        if (b > a) { ranges.push({a, b}); a = b = 0; paint(); }
      };
      $("spCut").onclick = async () => {
        if (b > a) { ranges.push({a, b}); a = b = 0; }
        if (!ranges.length) return;
        $("spCut").textContent = "cutting…";
        try {
          const got = await api.post("/api/samples/extract",
            {job_id: job, ranges});
          draw("done", "✓ " + got.made.length + " sample(s) cut into "
            + got.folder + " — the DJs have them in rotation now: "
            + got.made.join(", "));
          ranges = [];
        } catch (err) { draw("ready", err.message); }
      };
      paint();
    }
    $("spClose").onclick = () => { pop.style.display = "none"; };
    $("spFetch").onclick = () => fetchUrl($("spUrl").value.trim());
    if (stage === "idle") $("spUrl").focus();
  }

  async function fetchUrl(url) {
    if (!url) return;
    pop.style.display = "flex";
    draw("fetching", "fetching the media — fast path, no analysis…");
    $("spUrl").value = url;
    try {
      job = (await api.post("/api/samples/fetch", {url})).job_id;
      const t0 = Date.now();
      while (Date.now() - t0 < 600000) {
        await new Promise((r) => setTimeout(r, 4000));
        const st = await api.get("/api/samples/job/" + job);
        if (st.stage === "done" && st.audio) {
          audioUrl = st.audio; ranges = [];
          draw("ready", (st.title || "ready") + " — set IN/OUT off the "
            + "playhead, stack ranges, extract them all at once.");
          return;
        }
        if (st.stage === "error") {
          draw("idle", st.error || "that link would not fetch"); return;
        }
        draw("fetching", (st.stage || "working") + "… "
          + (st.note || ""));
      }
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

/* #831: the crystal switch — one click lets the crystal take the
 * universe; one click lifts it. Lit while any crystal is ON. */
function initCrystalBtn() {
  const btn = $("crystalBtn");
  if (!btn) return;
  let known = [];
  async function paint() {
    try {
      const d = await api.get("/api/crystals");
      known = d.crystals || [];
      const on = known.filter((c) => c.on);
      btn.classList.toggle("on", on.length > 0);
      btn.title = on.length
        ? "The universe is tinted: " + on.map((c) => c.name).join(", ")
          + " — click to lift it"
        : (known.length
           ? "Click to let " + known[known.length - 1].name
             + " tint the universe of Pine Box FM"
           : "No crystals forged yet — extract one from an artist first");
    } catch { /* agent quiet */ }
  }
  btn.addEventListener("click", async () => {
    if (!known.length) return;
    const anyOn = known.some((c) => c.on);
    btn.textContent = "…";
    try {
      for (const c of known) {
        if (anyOn && c.on) {
          await api.post("/api/crystals/" + c.id + "/toggle", {on: false});
        }
      }
      if (!anyOn) {
        const pick = known[known.length - 1];
        await api.post("/api/crystals/" + pick.id + "/toggle", {on: true});
      }
    } catch (err) { btn.title = err.message; }
    btn.textContent = "\ud83d\udd2e";
    paint();
  });
  paint();
  setInterval(paint, 30000);
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
})();
