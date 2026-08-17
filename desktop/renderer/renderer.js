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
  web: { label: "Web page", music: "here", voice: "here", reply: "here", voice_device: "pine", box_talk: false },
  app: { label: "Application", music: "off", voice: "here", reply: "here", voice_device: "pine", box_talk: false },
  nabu: { label: "Nabu", music: "off", voice: "box", reply: "box", voice_device: "nabu", box_talk: true }
};

const EMBEDDED_ROUTES = {
  box: { djOutput: "box", djVoiceOut: "box", djReplyOut: "box" },
  web: { djOutput: "here", djVoiceOut: "here", djReplyOut: "here" },
  app: { djOutput: "off", djVoiceOut: "here", djReplyOut: "here" },
  nabu: { djOutput: "off", djVoiceOut: "nabu", djReplyOut: "nabu" }
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
        const nextVolume = audible ? volume : 0;
        if (Math.abs(node.volume - nextVolume) > 0.001) node.volume = nextVolume;
        const muted = !audible || volume <= 0;
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
    if (typeof frame.setAudioMuted === "function") frame.setAudioMuted(!audible || appVolume <= 0);
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
  setDesiredBroadcast(desiredBroadcast || "nabu");
  try {
    await api.post("/api/dj/output", ROUTES[desiredBroadcast]);
    syncEmbeddedBroadcast(desiredBroadcast);
    noteRouteOk(`${ROUTES[desiredBroadcast].label} active`);
  } catch (err) {
    noteRouteError(err.message);
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

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => selectView(button.dataset.view));
});

$("refreshBtn").onclick = refresh;
$("openBrowserBtn").onclick = () => api.openExternal(config.baseUrl);
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
