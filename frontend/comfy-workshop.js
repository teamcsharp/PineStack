function node(tag, cls, text) {
  const out = document.createElement(tag);
  if (cls) out.className = cls;
  if (text != null) out.textContent = String(text);
  return out;
}

const PINE_BOX_LOGO = "/spark/asset/pinebox.png";

function duration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (!value) return "";
  const mins = Math.floor(value / 60);
  return mins + ":" + String(Math.round(value % 60)).padStart(2, "0");
}

function statusLabel(job) {
  const mode = String(job.mode || "text");
  const state = String(job.status || "queued");
  const files = job.files || [];
  return mode + " / " + state + (files.length ? " / " + files[0] : "");
}

export async function openComfyWorkshop({request, onClose=()=>{}}={}) {
  if (typeof request !== "function") {
    request = async (path, options={}) => {
      const response = await fetch(path, {cache:"no-store", ...options});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      return data;
    };
  }

  let alive = true;
  let timer = null;
  let data = {recent:[], clips:[], gallery:[], dialogue:[], jobs:[]};
  let tab = "recent";
  let mode = "text";
  let selected = null;
  let previewMedia = null;

  const shade = node("div", "cw-shade");
  const dialog = node("section", "cw-dialog");
  shade.id = "comfyWorkshopModal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "cwTitle");

  const header = node("header", "cw-header");
  const title = node("div", "cw-title");
  const heading = node("h2", "", "Comfy Workshop"); heading.id = "cwTitle";
  const engine = node("span", "cw-engine", "MiniMax H3");
  title.append(heading, engine);
  const admission = node("div", "cw-admission", "Reading the renderer");
  const refresh = node("button", "cw-icon", "Refresh"); refresh.title = "Refresh sources";
  const closeButton = node("button", "cw-icon", "Close"); closeButton.title = "Close Workshop";
  header.append(title, admission, refresh, closeButton);

  const body = node("div", "cw-body");
  const library = node("aside", "cw-library");
  const search = node("input", "cw-search");
  search.type = "search"; search.placeholder = "Search clips and gallery";
  search.setAttribute("aria-label", "Search Workshop sources");
  const tabs = node("nav", "cw-tabs"); tabs.setAttribute("aria-label", "Source shelf");
  const tabDefs = [["recent","On air"],["clips","Clip book"],["gallery","Gallery"]];
  const sourceList = node("div", "cw-sources");
  library.append(search, tabs, sourceList);

  const work = node("main", "cw-work");
  const preview = node("div", "cw-preview");
  preview.setAttribute("role", "group");
  preview.setAttribute("aria-label", "Source preview");
  preview.append(node("div", "cw-preview-empty", "No source selected"));
  const previewControls = node("div", "cw-preview-controls");
  const playPreview = node("button", "cw-play", "Play preview");
  playPreview.type = "button";
  playPreview.hidden = true;
  const scaleLabel = node("label", "cw-scale");
  scaleLabel.append(node("span", "", "Preview size"));
  const scale = node("input", "");
  scale.type = "range"; scale.min = "160"; scale.max = "480";
  scale.step = "20"; scale.value = "260";
  const scaleValue = node("output", "", "260 px");
  scaleLabel.append(scale, scaleValue);
  previewControls.append(playPreview, scaleLabel);
  const selectedName = node("div", "cw-selected", "Text to video");

  const modeBar = node("div", "cw-mode"); modeBar.setAttribute("role", "group");
  modeBar.setAttribute("aria-label", "Generation mode");
  const modeButtons = {};
  [["text","Text"],["frame","Frame"],["reference","Reference"]].forEach(([key,label]) => {
    const button = node("button", "", label);
    button.onclick = () => setMode(key);
    modeButtons[key] = button; modeBar.append(button);
  });

  const prompt = node("textarea", "cw-prompt");
  prompt.rows = 4; prompt.maxLength = 1800;
  prompt.placeholder = "Describe the shot, movement, setting, sound and dialogue";
  prompt.setAttribute("aria-label", "Video prompt");

  const speechRow = node("label", "cw-field");
  speechRow.append(node("span", "", "DJ line"));
  const speech = node("select", "");
  speech.append(new Option("No prepared line", ""));
  speechRow.append(speech);

  const options = node("div", "cw-options");
  const framesLabel = node("label", "cw-field"); framesLabel.append(node("span", "", "Length"));
  const frames = node("select", "");
  frames.append(new Option("Auto (3-7 seconds)", "auto"),
    new Option("Match reference", "reference"),
    new Option("Double reference", "double"));
  [3, 5, 7, 10, 12, 15].forEach((seconds) =>
    frames.append(new Option(seconds + " seconds", String(seconds))));
  framesLabel.append(frames);
  const stepsLabel = node("label", "cw-field"); stepsLabel.append(node("span", "", "Passes"));
  const steps = node("select", "");
  steps.append(new Option("4 / quick", "4"), new Option("6 / detail", "6"));
  stepsLabel.append(steps);
  const airLabel = node("label", "cw-check");
  const air = node("input", ""); air.type = "checkbox";
  airLabel.append(air, node("span", "", "Add finished clip to SFX rotation"));
  options.append(framesLabel, stepsLabel, airLabel);
  function lengthOptions() {
    const reference = mode === "reference" && selected && selected.kind === "video";
    Array.from(frames.options).forEach((option) => {
      if (option.value === "reference" || option.value === "double") {
        option.disabled = !reference;
      }
    });
    if (!reference && (frames.value === "reference" || frames.value === "double")) {
      frames.value = "auto";
    }
  }

  const action = node("div", "cw-action");
  const submit = node("button", "cw-submit", "Render video");
  const message = node("div", "cw-message", "Ready");
  action.append(submit, message);
  const jobsTitle = node("div", "cw-section-title", "Video queue");
  const jobs = node("div", "cw-jobs");
  work.append(preview, previewControls, selectedName, modeBar, prompt, speechRow, options,
              action, jobsTitle, jobs);
  body.append(library, work);
  dialog.append(header, body); shade.append(dialog); document.body.append(shade);
  let lastFocusedField = null;
  const originalParent = shade.parentNode;
  // The gallery can move this open dialog into its window; restore an editor blurred by that move.
  const moveObserver = typeof MutationObserver === "function"
    ? new MutationObserver(() => {
        if (!alive || shade.parentNode === originalParent) return;
        moveObserver.disconnect();
        if (lastFocusedField && shade.contains(lastFocusedField) &&
            (document.activeElement === document.body ||
             document.activeElement === document.documentElement)) {
          lastFocusedField.focus({preventScroll:true});
        }
      }) : null;
  if (moveObserver) moveObserver.observe(originalParent, {childList:true});
  shade.addEventListener("focusin", event => {
    if (event.target === prompt || event.target === search) lastFocusedField = event.target;
    dialog.classList.toggle("cw-editing", event.target === prompt);
  });
  shade.addEventListener("focusout", event => {
    if (event.target === prompt) dialog.classList.remove("cw-editing");
  });

  function setMessage(text, bad=false) {
    message.textContent = String(text || "");
    message.dataset.state = bad ? "error" : "ok";
  }

  function setMode(next) {
    mode = next;
    Object.entries(modeButtons).forEach(([key, button]) => {
      button.setAttribute("aria-pressed", String(key === mode));
    });
    selectedName.textContent = mode === "text"
      ? "Text to video"
      : (selected ? selected.name : "Choose a source");
    lengthOptions();
  }

  function stopPreview() {
    if (previewMedia && typeof previewMedia.pause === "function") {
      try { previewMedia.pause(); } catch (error) {}
    }
    previewMedia = null;
  }

  function updatePreviewSize() {
    preview.style.setProperty("--cw-preview-height", scale.value + "px");
    scaleValue.value = scale.value + " px";
    scaleValue.textContent = scaleValue.value;
  }

  function paintPreview() {
    stopPreview(); preview.replaceChildren();
    playPreview.hidden = true;
    if (!selected) {
      preview.append(node("div", "cw-preview-empty", "No source selected"));
      selectedName.textContent = mode === "text" ? "Text to video" : "Choose a source";
      return;
    }
    let media;
    if (selected.kind === "image") {
      media = node("img", ""); media.alt = selected.name || "Selected image";
      media.src = selected.url;
      media.onerror = () => {
        if (media.src !== new URL(PINE_BOX_LOGO, document.baseURI).href) {
          media.src = PINE_BOX_LOGO;
        }
      };
    } else if (selected.video) {
      media = node("video", ""); media.controls = true; media.muted = false;
      media.playsInline = true; media.preload = "auto";
      media.setAttribute("aria-label", "Preview " + (selected.name || "video"));
      media.dataset.ready = "false";
      const cover = node("div", "cw-video-fallback");
      cover.setAttribute("role", "status");
      const logo = node("img", ""); logo.src = PINE_BOX_LOGO; logo.alt = "";
      const coverStatus = node("span", "cw-sr-only", "Loading video preview");
      cover.append(logo, coverStatus);
      preview.append(cover);
      playPreview.hidden = false;
      playPreview.disabled = false;
      playPreview.textContent = "Play preview";
      const reveal = () => {
        if (previewMedia !== media || media.videoWidth <= 0) return;
        media.dataset.ready = "true";
        cover.hidden = true;
      };
      media.addEventListener("playing", () => {
        if (previewMedia !== media) return;
        playPreview.textContent = "Pause preview";
        if (typeof media.requestVideoFrameCallback === "function") {
          media.requestVideoFrameCallback(reveal);
        }
      });
      media.addEventListener("timeupdate", () => {
        if (media.dataset.ready === "false" && media.currentTime > 0.02) reveal();
      });
      media.addEventListener("pause", () => {
        if (previewMedia === media) playPreview.textContent = "Play preview";
      });
      media.addEventListener("ended", () => {
        if (previewMedia === media) playPreview.textContent = "Replay preview";
      });
      media.addEventListener("error", () => {
        if (previewMedia !== media) return;
        cover.hidden = false;
        coverStatus.className = "cw-video-error";
        coverStatus.textContent = "Video preview unavailable";
        playPreview.textContent = "Retry preview";
      });
      media.src = selected.url;
    } else {
      media = node("audio", ""); media.controls = true; media.preload = "metadata";
      media.src = selected.url;
    }
    previewMedia = media; preview.append(media);
    selectedName.textContent = selected.name + (selected.folder ? " / " + selected.folder : "");
  }

  function choose(item, sourceType) {
    selected = {...item, sourceType};
    if (mode === "text") setMode(item.kind === "audio" || item.kind === "video"
      ? "reference" : "frame");
    lengthOptions();
    paintPreview(); paintSources();
  }

  function paintTabs() {
    tabs.replaceChildren();
    tabDefs.forEach(([key,label]) => {
      const button = node("button", "", label);
      button.setAttribute("aria-pressed", String(tab === key));
      button.onclick = () => { tab = key; paintTabs(); paintSources(); };
      tabs.append(button);
    });
  }

  function paintSources() {
    sourceList.replaceChildren();
    const needle = search.value.trim().toLowerCase();
    const rows = (data[tab] || []).filter(item => !needle ||
      [item.name,item.folder].join(" ").toLowerCase().includes(needle));
    if (!rows.length) sourceList.append(node("div", "cw-empty", "Nothing found"));
    rows.forEach(item => {
      const row = node("button", "cw-source");
      const active = selected && selected.id === item.id && selected.sourceType ===
        (tab === "recent" ? "recent" : tab === "clips" ? "clip" : "gallery");
      row.setAttribute("aria-pressed", String(Boolean(active)));
      if (item.poster || item.video) {
        const image = node("img", ""); image.loading = "lazy"; image.alt = "";
        image.src = item.video ? PINE_BOX_LOGO : item.poster;
        if (item.video) image.classList.add("cw-source-logo");
        else image.onerror = () => {
          image.onerror = null;
          image.src = PINE_BOX_LOGO;
          image.classList.add("cw-source-logo");
        };
        row.append(image);
      } else {
        row.append(node("span", "cw-audio", "AUDIO"));
      }
      const copy = node("span", "cw-source-copy");
      copy.append(node("b", "", item.name || item.id),
                  node("small", "", [item.folder, duration(item.seconds)].filter(Boolean).join(" / ")));
      row.append(copy);
      row.onclick = () => choose(item, tab === "recent" ? "recent" : tab === "clips" ? "clip" : "gallery");
      sourceList.append(row);
    });
  }

  function paintDialogue() {
    const held = speech.value;
    speech.replaceChildren(new Option("No prepared line", ""));
    (data.dialogue || []).forEach(item => {
      const option = new Option(item.who + ": " + item.text, item.text);
      speech.append(option);
    });
    if ([...speech.options].some(option => option.value === held)) speech.value = held;
  }

  function paintJobs(rows=data.jobs || []) {
    jobs.replaceChildren();
    const videos = rows.filter(item => String(item.kind || "") === "video").slice(0, 10);
    if (!videos.length) jobs.append(node("div", "cw-empty", "No video jobs"));
    videos.forEach(item => {
      const row = node("div", "cw-job"); row.dataset.state = item.status || "queued";
      row.append(node("b", "", String(item.request || item.tags || "Video").slice(0, 110)),
                 node("span", "", statusLabel(item)));
      jobs.append(row);
    });
  }

  function paintAdmission(value) {
    const state = value || {};
    admission.dataset.state = state.ok ? "ok" : "held";
    admission.textContent = state.ok
      ? "Ready / " + (state.temperature_c == null ? "temperature unknown" : state.temperature_c + " C")
      : "Held / " + (state.why || "renderer is resting");
    submit.disabled = !state.ok;
  }

  async function load() {
    refresh.disabled = true;
    try {
      data = await request("/api/comfy/workshop");
      if (!alive) return;
      paintAdmission(data.admission); paintTabs(); paintSources();
      paintDialogue(); paintJobs();
    } catch (error) {
      if (alive) setMessage(error.message || error, true);
    } finally { refresh.disabled = false; }
  }

  async function pollJobs() {
    if (document.activeElement === prompt || document.activeElement === search) return;
    try {
      const out = await request("/api/generations?limit=40");
      if (alive) paintJobs(out.generations || []);
    } catch (error) {}
  }

  async function render() {
    if (mode !== "text" && !selected) {
      setMessage("Choose a source", true); return;
    }
    const spoken = speech.value;
    if (!prompt.value.trim() && !spoken) {
      setMessage("Enter a prompt or choose a DJ line", true); return;
    }
    submit.disabled = true; submit.textContent = "Submitting";
    let atShare = 0;
    if (previewMedia && previewMedia.tagName === "VIDEO" && previewMedia.duration) {
      atShare = previewMedia.currentTime / previewMedia.duration;
    }
    try {
      const out = await request("/api/comfy/workshop", {method:"POST", body:JSON.stringify({
        mode, prompt:prompt.value.trim(), speech:spoken,
        source:selected ? selected.id : "",
        source_type:selected ? selected.sourceType : "",
        at_share:atShare,
        duration_mode:frames.value === "reference" || frames.value === "double"
          ? frames.value : "auto",
        duration_seconds:/^\d+$/.test(frames.value) ? Number(frames.value) : undefined,
        steps:Number(steps.value),
        air_it:air.checked
      })});
      setMessage("Queued / " + out.prompt_id);
      await pollJobs();
    } catch (error) {
      setMessage(error.message || error, true);
    } finally {
      submit.disabled = false; submit.textContent = "Render video";
    }
  }

  function close() {
    if (!alive) return;
    alive = false; if (timer) clearInterval(timer); stopPreview();
    if (moveObserver) moveObserver.disconnect();
    try { shade.remove(); } catch (error) {}
    onClose();
  }

  refresh.onclick = load; closeButton.onclick = close;
  playPreview.onclick = async () => {
    const media = previewMedia;
    if (!media || media.tagName !== "VIDEO") return;
    if (!media.paused) { media.pause(); return; }
    if (media.error) {
      const status = preview.querySelector(".cw-video-error");
      if (status) {
        status.className = "cw-sr-only";
        status.textContent = "Loading video preview";
      }
      media.load();
    }
    try { await media.play(); }
    catch (error) {
      if (previewMedia === media) {
        playPreview.textContent = "Retry preview";
      }
    }
  };
  scale.addEventListener("input", updatePreviewSize);
  shade.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (shade.contains(document.activeElement) &&
        /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      event.stopPropagation();
      return;
    }
    close();
  });
  search.addEventListener("input", paintSources); submit.onclick = render;
  updatePreviewSize(); setMode("text"); load(); timer = setInterval(pollJobs, 8000);
  return {element:shade, close, resize:()=>{}, get selected(){return selected;}};
}
