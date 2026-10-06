<script>
/* [pinestream] PINESTREAM - THE PINETAB'S OR THE PINE APP'S OWN SCREEN, IN A
 * SMALL WINDOW OVER THE SHOW.
 *
 * The operator's switch is the master and this page never argues with it: the
 * station says show:false and the window goes, whatever this page wanted. What
 * a listener decides is only whether it is on THEIR screen - the X hides it
 * here (remembered in this browser), the chip brings it back. Neither reaches
 * the station.
 *
 * It rides the Pine Cam's own poll: /api/pinelink/mine carries a `pinestream`
 * block, handed here by news(), so PineStream adds no request to this page
 * while the switch is off. If that poll ever stops arriving, a slow fallback
 * asks /api/pinestream/mine itself.
 *
 * It comes on and goes off like the Pine Cam window: PineVcr, each switch flip
 * the station counted since the last answer replayed (PineVcr.flip), so a
 * listener sees every flip the operator made. The last frame is kept (hidden)
 * so a replayed opening shows a picture, not a hole.
 *
 * The picture is one JPEG in flight at a time, decoded offscreen, paced to the
 * operator's rate in the house and to one every two seconds or slower on the
 * car stream and the Funnel - never a queue behind the audio. A hidden tab, a
 * hidden window or a switched-off stream fetches nothing.
 */
(function () {
  var POS_KEY = "pbfm.pinestream.pos";
  var HIDE_KEY = "pbfm.pinestream.hidden";
  var box = null, bar = null, shot = null, veil = null, chip = null, what = null;
  var on = false;                 /* the station's word, for this viewer */
  var hidden = false;             /* this viewer's own choice */
  var state = "off", fps = 30, frameUrl = "", streamUrl = "", sourceName = "the PineTab", why = "";
  var streamConnected = false, streamRetry = 0;
  var lastFlips = null, newsAt = 0, pending = false, paceMs = 500, drawn = 0;
  try { hidden = localStorage.getItem(HIDE_KEY) === "1"; } catch (e) { hidden = false; }

  function icon(name) {
    try { return window.pineIcon ? (window.pineIcon(name) || "") : ""; } catch (e) { return ""; }
  }
  function onRoad() {
    var road = "house";
    try { road = currentRoad(); } catch (e) { road = "house"; }
    var car = false;
    try { car = (typeof streamMode !== "undefined") && !!streamMode; } catch (e) { car = false; }
    return car || road === "funnel";
  }
  function paceFloor() {
    return Math.round(1000 / Math.max(1, Math.min(60, fps || 30)));
  }
  function stamp(url) {
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now();
  }

  function clampTo(x, y) {
    if (!box) return;
    var w = box.offsetWidth || 300, h = box.offsetHeight || 200;
    var vw = window.innerWidth || 800, vh = window.innerHeight || 600;
    x = Math.max(4, Math.min(vw - w - 4, x));
    y = Math.max(4, Math.min(vh - h - 4, y));
    box.style.left = Math.round(x) + "px";
    box.style.top = Math.round(y) + "px";
    box.style.bottom = "auto";
  }
  function restorePos() {
    var p = null;
    try { p = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch (e) { p = null; }
    if (p && isFinite(p.x) && isFinite(p.y)) clampTo(p.x, p.y);
  }
  function drag() {
    var start = null;
    bar.addEventListener("pointerdown", function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest("button")) return;
      var r = box.getBoundingClientRect();
      start = {id: ev.pointerId, dx: ev.clientX - r.left, dy: ev.clientY - r.top};
      try { bar.setPointerCapture(ev.pointerId); } catch (e) {}
      box.classList.add("dragging");
      ev.preventDefault();
    });
    bar.addEventListener("pointermove", function (ev) {
      if (!start || ev.pointerId !== start.id) return;
      clampTo(ev.clientX - start.dx, ev.clientY - start.dy);
    });
    function end(ev) {
      if (!start || ev.pointerId !== start.id) return;
      start = null;
      box.classList.remove("dragging");
      try {
        var r = box.getBoundingClientRect();
        localStorage.setItem(POS_KEY, JSON.stringify({x: Math.round(r.left), y: Math.round(r.top)}));
      } catch (e) {}
    }
    bar.addEventListener("pointerup", end);
    bar.addEventListener("pointercancel", end);
    window.addEventListener("resize", function () {
      if (!box || !box.style.left) return;
      var r = box.getBoundingClientRect();
      clampTo(r.left, r.top);
    });
  }

  function build() {
    if (box) return;
    box = document.createElement("div");
    box.className = "pinestream";
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", "PineStream - the station's screen, live");
    bar = document.createElement("div");
    bar.className = "pinestream-bar";
    bar.title = "Drag to move PineStream";
    var dot = document.createElement("span");
    dot.className = "pinestream-dot";
    var name = document.createElement("b");
    name.textContent = "PineStream";
    what = document.createElement("span");
    what.className = "pinestream-what";
    bar.appendChild(dot);
    bar.appendChild(name);
    bar.appendChild(what);
    shot = document.createElement("img");
    shot.alt = "PineStream - the station's screen";
    veil = document.createElement("div");
    veil.className = "pinestream-veil";
    box.appendChild(bar);
    box.appendChild(shot);
    box.appendChild(veil);
    document.body.appendChild(box);
    /* the corner X: the house one where it loaded, the same Carbon X if not */
    var x = null;
    try { if (typeof window.pineCloseX === "function") x = window.pineCloseX(box, hide, {label: "Hide PineStream on this screen"}); } catch (e) { x = null; }
    if (!x) {
      x = document.createElement("button");
      x.type = "button";
      x.className = "pinestream-x";
      x.title = "Hide PineStream on this screen";
      x.setAttribute("aria-label", x.title);
      x.innerHTML = icon("c:close--filled") || "&times;";
      x.addEventListener("click", function (ev) { ev.stopPropagation(); hide(); });
      box.appendChild(x);
    }
    chip = document.createElement("button");
    chip.type = "button";
    chip.className = "pinestream-chip";
    chip.title = "Show PineStream - the station's screen, live";
    chip.setAttribute("aria-label", chip.title);
    chip.innerHTML = (icon("c:screen") || "") + "<span>PineStream</span>";
    chip.hidden = true;
    chip.addEventListener("click", function (ev) { ev.stopPropagation(); show(); });
    document.body.appendChild(chip);
    drag();
    restorePos();
  }

  function vcr(want, burst) {
    if (want) build();
    if (!box) return;
    var V = window.PineVcr;
    var o = {
      show: function () { box.classList.add("show"); draw(); },
      hide: function () { if (!(on && !hidden)) box.classList.remove("show"); }
    };
    if (!V) { if (want) o.show(); else box.classList.remove("show"); return; }
    if (burst > 0) V.flip(box, want, burst, o); else V.set(box, want, o);
  }
  function paint() {
    if (!box) return;
    what.textContent = sourceName ? "· " + sourceName : "";
    var words = "";
    if (state === "waiting") words = "Waiting for the picture from " + sourceName + "...";
    else if (state === "private") words = "Private screen" + (why ? " - " + why : "") + ". Back in a moment.";
    veil.textContent = words;
    veil.hidden = !words;
    box.classList.toggle("private", state === "private");
    if (chip) chip.hidden = !(on && hidden);
  }
  function hide() {
    hidden = true;
    stopStream();
    try { localStorage.setItem(HIDE_KEY, "1"); } catch (e) {}
    vcr(false, 0);
    paint();
  }
  function show() {
    hidden = false;
    try { localStorage.removeItem(HIDE_KEY); } catch (e) {}
    if (on) vcr(true, 0);
    paint();
  }

  function stopStream() {
    if (!streamConnected) return;
    streamConnected = false;
    if (shot) shot.removeAttribute('src');
  }
  function draw() {
    if (streamUrl) {
      if (!on || hidden || document.hidden || !shot || (state !== 'live' && state !== 'waiting')) { stopStream(); return; }
      if (streamConnected || Date.now() < streamRetry) return;
      streamConnected = true;
      shot.onload = function () {
        if (!streamConnected || !on || hidden || document.hidden) return;
        drawn += 1;
        if (state === 'waiting') { state = 'live'; paint(); }
      };
      shot.onerror = function () { stopStream(); streamRetry = Date.now() + 300; };
      shot.src = stamp(streamUrl);
      return;
    }
    if (!on || hidden || !frameUrl || state !== "live" || !shot) return;
    if (document.hidden || pending) return;
    pending = true;
    var t0 = Date.now();
    var img = new Image();
    img.onload = function () {
      pending = false;
      var took = Date.now() - t0;
      paceMs = Math.max(paceFloor(), Math.min(6000, Math.round(paceMs * 0.5 + took * 0.8)));
      if (shot && on && !hidden && !document.hidden && !streamUrl) { shot.src = img.src; drawn += 1; }
    };
    img.onerror = function () {
      pending = false;
      paceMs = Math.min(6000, paceMs * 2);      /* back off; the last frame stays */
    };
    img.src = stamp(frameUrl);
  }
  function drawLoop() {
    try { draw(); } catch (e) { pending = false; }
    setTimeout(drawLoop, streamUrl ? 250 : Math.max(paceFloor(), paceMs));
  }

  /* One answer from the station: the pinestream block of /api/pinelink/mine,
   * or of /api/pinestream/mine when the fallback asked. */
  function news(got) {
    newsAt = Date.now();
    if (!got || typeof got !== "object") return;
    var want = !!got.show;
    state = String(got.state || (want ? "waiting" : "off"));
    fps = Number(got.fps) || 30;
    frameUrl = String(got.frame || "");
    var nextStream = String(got.stream || "");
    if (nextStream !== streamUrl) { stopStream(); streamRetry = 0; }
    streamUrl = nextStream;
    sourceName = String(got.source_name || "the PineTab");
    why = String(got.why || "");
    var sw = got.switch || null;
    var flips = sw ? Number(sw.flips || 0) : 0;
    var burst = (sw && sw.yours && lastFlips !== null && flips > lastFlips) ? flips - lastFlips : 0;
    if (sw) lastFlips = flips;
    if (want !== on || burst) {
      on = want;
      if (!hidden) vcr(on, burst);
    }
    if (on) build();
    paint();
    draw();
  }
  async function fallback() {
    if (Date.now() - newsAt < 12000) return;
    try {
      news(await api("/api/pinestream/mine"));
    } catch (e) {
      newsAt = Date.now();
      if (on) { on = false; stopStream(); vcr(false, 0); paint(); }
    }
  }
  function fallbackLoop() {
    try { fallback(); } catch (e) {}
    setTimeout(fallbackLoop, document.hidden ? 30000 : 6000);
  }
  document.addEventListener("visibilitychange", function () {
    try { draw(); } catch (e) {}
  });
  window.PineStreamTune = {
    news: news, show: show, hide: hide,
    state: function () {
      return {on: on, hidden: hidden, picture: state, fps: fps, drawn: drawn, paceMs: paceMs, transport: streamUrl ? 'live' : 'snapshots', connected: streamConnected,
              vcr: (box && window.PineVcr) ? window.PineVcr.state(box) : (box ? "none" : "unbuilt"),
              chip: !!(chip && !chip.hidden)};
    }
  };
  drawLoop();
  setTimeout(fallbackLoop, 15000);
})();
</script>
