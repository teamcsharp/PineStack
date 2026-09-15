/* The trim editor - tighten a grabbed moment to the exact phrase.
 *
 * The station cuts what it knows: a whole booth line, or the welded round
 * it aired in. Neither is necessarily the bit worth keeping, and
 * X-Pine-Exact: 0 says so out loud. This is where the operator takes the
 * seven seconds he was handed and keeps the one that is funny.
 *
 * Nothing here is destructive. The trim is two numbers in the pad's record;
 * the decoded audio is never touched, so every edit is reversible and
 * "reset" is genuinely a reset rather than a re-download.
 */
(function (root) {
  "use strict";

  const engine = () => root.pineSampler;
  const sampler = () => root.PineSampler;

  let overlay = null;
  let canvas = null;
  let bankIndex = 0;
  let padIndex = 0;
  let meta = null;
  let key = "";
  let dragging = "";        /* "start" | "end" | "" */
  let previewVoice = "";

  function seconds() { return engine().seconds(key) || 0; }

  function draw() {
    if (!canvas) return;
    const width = canvas.width = canvas.clientWidth * (root.devicePixelRatio || 1);
    const height = canvas.height = canvas.clientHeight * (root.devicePixelRatio || 1);
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, width, height);

    const total = seconds();
    if (!total) return;
    const peaks = engine().peaks(key, Math.max(64, Math.floor(width / 2)));
    const middle = height / 2;

    /* The kept window is drawn bright against a dimmed whole, so the shape
     * of what was thrown away stays visible - it is often the reason the
     * operator wants to nudge a handle back. */
    const trim = meta.trim || { start: 0, end: total };
    const startX = (trim.start / total) * width;
    const endX = (trim.end / total) * width;

    for (let i = 0; i < peaks.length; i += 1) {
      const x = (i / peaks.length) * width;
      const amplitude = Math.max(1, peaks[i] * middle * 0.95);
      const inside = x >= startX && x <= endX;
      context.fillStyle = inside ? "#7fd4ff" : "#2b3b4a";
      context.fillRect(x, middle - amplitude, Math.max(1, width / peaks.length), amplitude * 2);
    }

    context.fillStyle = "rgba(0,0,0,.45)";
    context.fillRect(0, 0, startX, height);
    context.fillRect(endX, 0, width - endX, height);

    for (const [x, colour] of [[startX, "#8ef6b0"], [endX, "#ff9b7a"]]) {
      context.fillStyle = colour;
      context.fillRect(x - 1, 0, 3, height);
    }
  }

  function secondsAt(event) {
    const box = canvas.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / Math.max(1, box.width);
    return Math.max(0, Math.min(1, ratio)) * seconds();
  }

  function commit() {
    sampler().applySettings(key, meta);
    sampler().layout()[bankIndex][padIndex] = meta;
    sampler().save();
    sampler().repaint();
    draw();
    stamp();
  }

  function stamp() {
    const total = seconds();
    const trim = meta.trim || { start: 0, end: total };
    const readout = document.getElementById("pbTrimReadout");
    if (readout) {
      readout.textContent = trim.start.toFixed(3) + "s → " + trim.end.toFixed(3)
        + "s  (" + (trim.end - trim.start).toFixed(3) + "s of " + total.toFixed(3) + "s)";
    }
  }

  function preview() {
    if (previewVoice) { engine().release(previewVoice); previewVoice = ""; }
    previewVoice = engine().fire(key, { velocity: 1 });
  }

  function close() {
    if (previewVoice) { engine().release(previewVoice); previewVoice = ""; }
    if (overlay) overlay.hidden = true;
  }

  function build() {
    overlay = document.createElement("div");
    overlay.className = "pb-trim";
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="pb-trim-box">'
      + '<div class="pb-trim-head"><b id="pbTrimTitle">Pad</b>'
      + '<button id="pbTrimClose" title="Close" aria-label="Close">✕</button></div>'
      + '<p id="pbTrimCut" class="pb-trim-cut"></p>'
      + '<canvas id="pbTrimCanvas" class="pb-trim-canvas"></canvas>'
      + '<p id="pbTrimReadout" class="pb-trim-readout"></p>'
      + '<div class="pb-trim-row">'
      + '<label>gain <input id="pbTrimGain" type="range" min="0" max="200" step="1"></label>'
      + '<label>tune <input id="pbTrimPitch" type="range" min="-12" max="12" step="1"></label>'
      + '</div>'
      + '<div class="pb-trim-row">'
      + '<button id="pbTrimLoop" class="pb-mode">LOOP</button>'
      + '<button id="pbTrimRev" class="pb-mode">REVERSE</button>'
      + '<button id="pbTrimPlay" class="pb-mode">▶ PREVIEW</button>'
      + '<button id="pbTrimReset" class="pb-mode">RESET</button>'
      + '<button id="pbTrimClear" class="pb-mode danger">CLEAR PAD</button>'
      + '</div></div>';
    document.body.appendChild(overlay);
    canvas = document.getElementById("pbTrimCanvas");

    overlay.addEventListener("pointerdown", (event) => {
      if (event.target === overlay) close();
    });
    document.getElementById("pbTrimClose").addEventListener("click", close);
    document.getElementById("pbTrimPlay").addEventListener("click", preview);

    canvas.addEventListener("pointerdown", (event) => {
      const total = seconds();
      if (!total) return;
      const at = secondsAt(event);
      const trim = meta.trim || { start: 0, end: total };
      dragging = Math.abs(at - trim.start) <= Math.abs(at - trim.end) ? "start" : "end";
      meta.trim = { start: trim.start, end: trim.end };
      canvas.setPointerCapture(event.pointerId);
      moveHandle(at);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      moveHandle(secondsAt(event));
    });
    const release = () => {
      if (!dragging) return;
      dragging = "";
      /* Snap only when the handle is put down, not while it is moving -
       * snapping under a live drag makes the handle feel like it is
       * fighting the finger. */
      meta.trim.start = engine().zeroCross(key, meta.trim.start);
      meta.trim.end = engine().zeroCross(key, meta.trim.end);
      commit();
    };
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", release);

    const gain = document.getElementById("pbTrimGain");
    gain.addEventListener("input", () => {
      meta.gain = Number(gain.value) / 100;
      commit();
    });
    const pitch = document.getElementById("pbTrimPitch");
    pitch.addEventListener("input", () => {
      meta.pitch = Math.pow(2, Number(pitch.value) / 12);
      commit();
    });

    document.getElementById("pbTrimLoop").addEventListener("click", (event) => {
      meta.loop = !meta.loop;
      event.target.classList.toggle("on", meta.loop);
      commit();
    });
    document.getElementById("pbTrimRev").addEventListener("click", (event) => {
      meta.reverse = !meta.reverse;
      event.target.classList.toggle("on", meta.reverse);
      commit();
    });
    document.getElementById("pbTrimReset").addEventListener("click", () => {
      meta.trim = null;
      meta.gain = 1;
      meta.pitch = 1;
      gain.value = "100";
      pitch.value = "0";
      commit();
    });
    document.getElementById("pbTrimClear").addEventListener("click", async () => {
      await sampler().forget(bankIndex, padIndex);
      close();
    });

    root.addEventListener("resize", () => { if (!overlay.hidden) draw(); });
  }

  function moveHandle(at) {
    const total = seconds();
    const guard = Math.min(0.01, total / 50);
    if (dragging === "start") meta.trim.start = Math.min(at, meta.trim.end - guard);
    else meta.trim.end = Math.max(at, meta.trim.start + guard);
    meta.trim.start = Math.max(0, meta.trim.start);
    meta.trim.end = Math.min(total, meta.trim.end);
    draw();
    stamp();
  }

  function open(b, p) {
    if (!overlay) build();
    bankIndex = b;
    padIndex = p;
    key = sampler().padKey(b, p);
    meta = sampler().layout()[b][p];
    if (!meta || !engine().loaded(key)) return;
    if (!meta.trim) meta.trim = null;

    document.getElementById("pbTrimTitle").textContent =
      "Pad " + (p + 1) + " · bank " + (b + 1) + " — " + (meta.label || "");
    const cut = document.getElementById("pbTrimCut");
    cut.textContent = meta.exact === false
      ? (meta.cut || "The station could not cut this line exactly.")
      : "";
    cut.hidden = meta.exact !== false;

    document.getElementById("pbTrimGain").value = String(Math.round((meta.gain == null ? 1 : meta.gain) * 100));
    document.getElementById("pbTrimPitch").value =
      String(Math.round(Math.log2(meta.pitch == null ? 1 : meta.pitch) * 12));
    document.getElementById("pbTrimLoop").classList.toggle("on", !!meta.loop);
    document.getElementById("pbTrimRev").classList.toggle("on", !!meta.reverse);

    overlay.hidden = false;
    draw();
    stamp();
  }

  root.PineSamplerTrim = { open, close };
})(typeof window !== "undefined" ? window : globalThis);
