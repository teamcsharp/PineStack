/* pine-boot/boot-sequence.js - the terminal assembling itself.
 *
 * TWO PHASES, ONE FILE.
 *
 *   PHASE 1  a three.js scene of the station's own ten-stage spine building
 *            itself out of off-screen parts, with a console overlay naming
 *            what is actually happening while the panel loads behind it.
 *   PHASE 2  the panel arriving: its top-level sections transformed in from
 *            off-screen, staggered, and then stripped of every transform.
 *
 * Injected at DOCUMENT START (WebViewCompat.addDocumentStartJavaScript via
 * BootAssets.kt), so the overlay is up before the panel's own two megabytes
 * begin to paint. Everything the console says is measured here or read off
 * the panel's own first /api/dj - nothing on this screen is invented. A boot
 * screen that lies is a poor way to open an application.
 *
 * ---------------------------------------------------------------------------
 * WHY THE TEN STAGES AND NOT A PROGRESS BAR
 *
 * The station is one assembly line - ideation, writing, crystal, tint,
 * grader, recording, stores, schedule, air, learning (docs/RapAssembly.md) -
 * and the panel already draws that line in its own 3js view. So the boot
 * scene is that same line, in the same visual language (the same box, the
 * same 0x1a2438 body with a per-stage emissive, the same 0x22304a
 * connectors, the same travelling packets, the same 9-unit pitch), built one
 * block at a time. Each block is landed by ONE REAL BOOT FACT, so what you
 * are watching is the terminal finding the station, not a timer.
 *
 *     IDEATION   the terminal window exists, and how wide it laid out
 *     WRITING    the geometry engine, read out of the APK (no network)
 *     CRYSTAL    GET /healthz - the station is reachable, and how quickly
 *     TINT       the panel's first /api/dj leaves, with or without a bearer
 *     GRADER     that request answers: bytes, milliseconds
 *     RECORDING  the audio engine that actually loaded (Oboe or Web Audio)
 *     STORES     the cupboard and pantry numbers out of that same answer
 *     SCHEDULE   on / paused / music_to / voice_to, the routing
 *     AIR        `now` - what is playing this second
 *     LEARNING   the panel document itself finishing
 *
 * A block that lands on a fact that did NOT hold - no station, no bearer,
 * no audio engine - lands DIM and says so. The line is a report, not a
 * decoration, and a decoration that shows ten green lights over a dead
 * station is worse than no screen at all.
 *
 * ---------------------------------------------------------------------------
 * THE FOUR CONSTRAINTS THIS FILE IS WRITTEN AGAINST
 *
 * 1. THREE.JS IS 593 kB AND MUST NOT BE DOWNLOADED. It ships in the APK and
 *    is handed over as a string by BootAssets' JavaScript interface - a read
 *    off local flash, never a socket. The panel's own lazy
 *    `<script src="/vendor/three.min.js">` is the measured three-MINUTE stall
 *    on this tablet (PineNet.kt has the numbers); this never touches it.
 *    And phase 1 does not WAIT for it either: the console and the frame paint
 *    on the first frame, and the scene is upgraded in when the engine
 *    arrives. If it never arrives the console alone is still a complete and
 *    honest boot screen, and the sequence still ends on time.
 *
 * 2. IT MUST NEVER DELAY THE APP. The panel loads behind the overlay the
 *    whole time. The overlay leaves the moment the panel is ready past a
 *    950 ms floor, and leaves regardless at a 4000 ms cap. On this tablet the
 *    panel is measured ready at 2.8-5.7 s, so the floor is never the binding
 *    constraint and the sequence costs the launch nothing.
 *
 * 2b. THE PANEL OWNS THE MAIN THREAD FOR EXACTLY THIS WINDOW, measured, so
 *    the scene runs on a WORKER against an OffscreenCanvas and the page's
 *    thread is not asked for anything it cannot spare. The long note above
 *    PINE_SCENE has the numbers.
 *
 * 3. THE DEVICE HAS 4 GB AND HAS KILLED THIS WEBVIEW BEFORE. One shared box
 *    geometry, one shared sphere geometry, ten label textures, and a teardown
 *    that disposes every geometry, material and texture, calls
 *    renderer.dispose() AND forceContextLoss(), zeroes the canvas and drops
 *    the RAF. A leaked WebGL context here is a crash, not a smell.
 *
 * 4. TOUCH. Every canvas gets `touch-action: none` or the WebView claims the
 *    gesture and fires pointercancel at the page - measured on this device.
 *    The overlay takes a tap as "skip", which is the only gesture it wants.
 */
(function (win) {
  "use strict";

  /* Frames, not windows: an iframe must never open a boot sequence. */
  if (win.top !== win) return;

  /* ONCE PER LAUNCH, and the guard is native on purpose.
   *
   * `window.__pineBootBooted` would only guard ONE document, and this script
   * is registered for every navigation - the rail's quick jumps included. A
   * flag in sessionStorage would survive a process death it should not. So
   * the native side hands out exactly one claim per activity, and every later
   * navigation gets `false` and returns here. onPageStarted firing twice for
   * one page cannot double-build either. */
  var native = win.__pineBootNative;
  if (!native) return;
  try { if (native.claim() !== true) return; } catch (err) { return; }

  /* --------------------------------------------------------------------- */
  /* Dials                                                                  */
  /* --------------------------------------------------------------------- */

  var FLOOR_MS = 1050;     /* the shortest the scene may be ON SCREEN       */
  var GRACE_MS = 500;      /* how long stragglers may hold it past the floor */
  var CAP_MS = 4000;       /* above this the app is more important than it  */
  var HARD_CAP_MS = 5200;  /* the ceiling even when first paint was late    */
  var STAGGER_MS = 45;     /* the shortest gap between two blocks landing   */
  var SLIDE_STEP_MS = 50;  /* phase 2 stagger                               */
  var SLIDE_MS = 280;      /* phase 2 per-element travel                    */
  var SWAY = 0.055;        /* how far the line drifts; the fit allows for it */
  /* THE ASSEMBLY IS TIMED AGAINST THE FRAMES THIS DEVICE ACTUALLY GIVES.
     Measured on the tablet, the page produces SEVEN TO NINE frames in the
     whole window the overlay is on screen, because the panel's own boot
     scripts own the thread. So the last block is released at 9 * 45 = 405 ms
     and lands 320 ms later - the whole line is built inside 725 ms, which
     fits the 1050 ms floor with room to be looked at. Slower and prettier
     numbers produce a line that is still half-built when it fades, which is
     what the first tuning did. */
  var SLIDE_MOST = 7;      /* 6 * 50 + 280 = 580 ms worst case              */

  var t0 = (win.performance && performance.now) ? performance.now() : Date.now();
  function now() {
    return (win.performance && performance.now) ? performance.now() : Date.now();
  }
  function since() { return Math.round(now() - t0); }

  var finished = false;
  var panelReady = false;
  var djSeen = false;
  var landedCount = 0;

  /* WHEN THE OVERLAY CAN ACTUALLY BE SEEN, which is not when it is built.
   *
   * Measured on the tablet: the overlay existed from 17 ms and the screen
   * was still the WebView's bare background at 1000 ms. Chromium will not
   * perform a document''s first paint until rendering is unblocked, and this
   * panel blocks it hard - 2.18 MB of HTML, served with NO content-encoding,
   * whose <head> is one enormous inline <style> that must be received and
   * parsed in full before anything at all may be drawn. Nothing the page can
   * do changes that; the overlay simply cannot paint first.
   *
   * So three things hang off this moment rather than off document start:
   * the native "Reaching the station" view is not taken down until there is
   * something to replace it with (otherwise the operator gets a BLACK screen
   * for a second and a half, which is exactly what the first build did), the
   * assembly does not begin until someone can watch it, and the on-screen
   * floor is counted from here.
   */
  var paintedAt = null;
  function markPainted(how) {
    if (paintedAt !== null) return;
    paintedAt = now();
    try { native.log("first paint at " + since() + "ms (" + how + ")"); } catch (e) {}
    try { native.painted(); } catch (e) {}
  }
  function sincePaint() { return paintedAt === null ? -1 : Math.round(now() - paintedAt); }
  /* FIRST-CONTENTFUL-PAINT, AND THEN TWO MORE FRAMES, and both halves of
     that were bought with a bad launch.
     `first-paint` alone fires for a frame that may carry only a background,
     and on one measured run it fired at 1242 ms on a page that then produced
     NOTHING for six seconds - so the native panel came down and the operator
     watched a blank screen. FCP means a frame with real content in it, and
     waiting two further animation frames on top proves the page is still
     producing frames rather than having managed exactly one. When it has
     not, the native "Reaching the station" view is left up, which is the
     correct thing to show while nothing else can be. */
  function armPaint(how) {
    if (paintedAt !== null) return;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { markPainted(how); });
    });
  }
  try {
    var po = new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) {
        if (e.name === "first-contentful-paint") armPaint("fcp+2");
      });
    });
    po.observe({ type: "paint", buffered: true });
  } catch (e) { /* no PerformanceObserver: the fallback below covers it */ }
  /* A belt for the braces. The native panel comes down on its own from
     MainActivity too, so this can only ever be early, never load-bearing. */
  setTimeout(function () { markPainted("fallback"); }, 3000);

  /* --------------------------------------------------------------------- */
  /* The ten stages                                                         */
  /* --------------------------------------------------------------------- */

  var STAGES = [
    { key: "ideation",  face: "IDEATION",   color: 0x4bb3ff },
    { key: "writing",   face: "WRITING",    color: 0x5fa8ff },
    { key: "crystal",   face: "CRYSTAL",    color: 0xb48cff },
    { key: "tint",      face: "TINT",       color: 0xc79bff },
    { key: "grader",    face: "GRADER",     color: 0x2ee08a },
    { key: "recording", face: "RECORDING",  color: 0xffb35e },
    { key: "stores",    face: "STORES",     color: 0xffd479 },
    { key: "schedule",  face: "SCHEDULE",   color: 0x9de3ef },
    { key: "air",       face: "ON THE AIR", color: 0xffffff },
    { key: "learning",  face: "LEARNING",   color: 0x3fd0c0 }
  ];
  var INDEX = {};
  STAGES.forEach(function (s, i) { INDEX[s.key] = i; s.claimed = false; s.lit = false; });

  /* A stage is CLAIMED the moment its fact arrives and RELEASED by the drain
     clock, never faster than STAGGER_MS after the previous release. Ten facts
     arriving in one tick is ten boxes appearing at once, which reads as a
     glitch rather than an assembly. The drain runs on its own clock and NOT
     inside the render loop, so the sequence still finishes on time on a
     device that never gets a WebGL context. */
  var queue = [];
  var released = [];
  var lastRelease = -1e9;
  function land(key, lit) {
    var s = STAGES[INDEX[key]];
    if (!s || s.claimed) return;
    s.claimed = true;
    s.lit = lit !== false;
    queue.push(s);
  }

  /* Set by build(); null until (or unless) three.js arrives. */
  var scene3 = null;

  /* THE DRAIN CATCHES UP RATHER THAN FALLING BEHIND, and that is not a
   * nicety on this device.
   *
   * Measured: the panel's own scripts are a 2.1 MB document's worth of
   * inline JavaScript compiled and run on an MT6768, and they own the ONE
   * main thread from first paint onwards. In that window a 30 ms interval
   * was observed firing roughly once a second and rAF with it, so releasing
   * exactly one block per tick built two blocks in the whole sequence and
   * the line never assembled.
   *
   * So a tick that arrives late releases everything that tick was owed,
   * with a small cascade so the catch-up still reads as an assembly rather
   * than a pop. The clock is the authority; the tick is only when we get to
   * look at it.
   */
  setInterval(function () {
    if (finished || !queue.length) return;
    /* Nothing assembles before there is a screen to assemble on. */
    if (paintedAt === null) return;
    var owed = Math.floor((now() - lastRelease) / STAGGER_MS);
    if (owed < 1) return;
    lastRelease = now();
    for (var k = 0; k < owed && queue.length; k += 1) {
      var s = queue.shift();
      released.push(s);
      landedCount += 1;
      if (scene3) scene3.arrive(s, k * 0.06);
    }
    rule.style.width = Math.round(landedCount / STAGES.length * 100) + "%";
  }, 30);

  /* --------------------------------------------------------------------- */
  /* The overlay                                                            */
  /* --------------------------------------------------------------------- */

  var root = document.createElement("div");
  root.id = "pine-boot";
  /* NOT class="view". The station panel owns `.view` and its own switcher
     would turn this straight off - the same collision the sampler hit. */
  root.setAttribute("role", "presentation");

  var style = document.createElement("style");
  style.id = "pine-boot-css";
  style.textContent = [
    "#pine-boot{position:fixed;inset:0;z-index:2147483600;background:#03060b;",
    "overflow:hidden;touch-action:none;-webkit-user-select:none;user-select:none;",
    "font-family:ui-monospace,Menlo,Consolas,monospace;contain:layout paint}",
    "#pine-boot.pine-boot-out{opacity:0;transition:opacity 240ms linear;pointer-events:none}",
    "#pine-boot canvas{position:absolute;inset:0;width:100%;height:100%;",
    "display:block;touch-action:none}",
    "#pine-boot .pb-chrome{position:absolute;inset:0;pointer-events:none}",
    "#pine-boot .pb-title{position:absolute;top:13px;left:18px;color:#9de3ef;",
    "font:700 13px/1.2 ui-monospace,monospace;letter-spacing:.16em}",
    "#pine-boot .pb-sub{position:absolute;top:32px;left:18px;color:#3c5871;",
    "font:400 10px/1.2 ui-monospace,monospace;letter-spacing:.08em}",
    "#pine-boot .pb-log{position:absolute;left:18px;bottom:24px;right:18px;",
    "color:#7fa6c0;font:400 11px/1.5 ui-monospace,monospace;",
    "white-space:pre;overflow:hidden}",
    "#pine-boot .pb-log b{color:#d6ecf8;font-weight:400}",
    "#pine-boot .pb-log i{color:#3f5f7a;font-style:normal}",
    "#pine-boot .pb-rule{position:absolute;left:0;bottom:0;height:2px;",
    "background:#9de3ef;width:0;transition:width 240ms linear;opacity:.85}",
    "#pine-boot .pb-skip{position:absolute;right:18px;bottom:20px;color:#2b4256;",
    "font:400 10px/1 ui-monospace,monospace;letter-spacing:.14em}",
    /* Phase 2 needs the page not to grow a horizontal scrollbar while the
       sections are still off to the side. Removed when it is done. */
    "html.pine-boot-sliding{overflow-x:hidden !important}"
  ].join("");

  var chrome = document.createElement("div");
  chrome.className = "pb-chrome";
  var title = document.createElement("div");
  title.className = "pb-title";
  title.textContent = "PINE BOX · ASSEMBLING THE STATION";
  var sub = document.createElement("div");
  sub.className = "pb-sub";
  sub.textContent = "ideation · writing · crystal · tint · grader · recording · stores · schedule · air · learning";
  var logBox = document.createElement("div");
  logBox.className = "pb-log";
  var rule = document.createElement("div");
  rule.className = "pb-rule";
  var skip = document.createElement("div");
  skip.className = "pb-skip";
  skip.textContent = "TAP TO SKIP";
  chrome.appendChild(title);
  chrome.appendChild(sub);
  chrome.appendChild(logBox);
  chrome.appendChild(rule);
  chrome.appendChild(skip);
  root.appendChild(chrome);

  var LINES_MOST = 11;
  var lines = [];
  function pushLine(text) {
    var stamp = String(since());
    while (stamp.length < 4) stamp = "0" + stamp;
    lines.push("<i>[" + stamp + "]</i> " + text);
    if (lines.length > LINES_MOST) lines.shift();
    logBox.innerHTML = lines.join("\n");
  }
  function say(text) {
    /* After the handover the console is gone, but a fact that was still in
       flight is worth keeping - /api/dj taking five seconds is exactly the
       sort of thing worth finding in logcat later. So it is still logged;
       only the DOM write is skipped. */
    if (!finished) pushLine(text);
    /* Also to logcat, so the sequence can be measured with
       `adb logcat -s PineBoot` rather than by squinting at screenshots. */
    try { native.log(since() + "ms  " + text.replace(/<[^>]+>/g, "")); } catch (err) {}
  }

  /* At document start there is a documentElement and usually no body. The
     overlay goes in wherever it can and is re-parented into the body as soon
     as one exists - re-parenting a canvas does not cost its WebGL context. */
  function attach() {
    try {
      var head = document.head || document.documentElement;
      if (head && !document.getElementById("pine-boot-css")) head.appendChild(style);
      var host = document.body || document.documentElement;
      if (!host) return false;
      if (root.parentNode !== host) host.appendChild(root);
      return true;
    } catch (err) { return false; }
  }
  attach();
  /* AS SOON AS THERE IS A BODY, not at DOMContentLoaded.
   *
   * At document start there is no <body>, so the overlay goes under <html>.
   * Chromium renders that, but waiting until DOMContentLoaded to move it -
   * measured at 1.3 to 2.7 s on this panel - left the scene parented outside
   * the body for most of its life. A MutationObserver on documentElement
   * catches the body the instant the parser creates it, and disconnects. */
  if (!document.body && win.MutationObserver) {
    var watcher = new MutationObserver(function () {
      if (!document.body) return;
      watcher.disconnect();
      attach();
    });
    try { watcher.observe(document.documentElement, { childList: true }); } catch (e) {}
  }
  document.addEventListener("DOMContentLoaded", attach);

  /* Tap to skip - the only gesture this screen wants, and the reason the
     overlay is not pointer-events:none. */
  /* THE LOGO ASSEMBLES IN THE MIDDLE OF THE BOOT SCREEN.
   *
   * The scene this file was written around runs on a Worker against an
   * OffscreenCanvas, and measured on the device it puts NOTHING on screen -
   * the boot screen shows its title, its rule and its log over an empty
   * middle. That space is where the mark belongs, so the assembly is drawn
   * into it on the main thread, where it is known to render.
   *
   * It is decoration and is treated as such: if the splash is missing, the
   * logo is missing, or anything throws, the boot screen is exactly what it
   * was before. */
  if (win.PineBootSplash && win.__pineLogo) {
    try {
      win.PineBootSplash.show({ src: win.__pineLogo, into: root });
    } catch (err) { /* the boot must not wait on a picture */ }
  }

  root.addEventListener("pointerdown", function () { finish("tapped"); }, { passive: true });

  /* --------------------------------------------------------------------- */
  /* The facts                                                              */
  /* --------------------------------------------------------------------- */

  /* 1. IDEATION - this window.
   *
   * The second line measures THE WINDOW THIS SEQUENCE CANNOT COVER. An
   * overlay can only exist once the document does, and the document only
   * exists once the station has answered with the first bytes of a 2.1 MB
   * uncompressed HTML page. `performance.now()` here IS the time-to-first-
   * byte, because timeOrigin is navigationStart; everything before that -
   * the key-discovery round trip, the connect - is the difference against
   * the native clock. Both are printed so the gap can be attacked at the
   * right end rather than guessed at. */
  say("terminal up · " + (win.screen ? screen.width + "x" + screen.height : "?")
    + " device px, laid out at " + win.innerWidth + "x" + win.innerHeight + " css px");
  land("ideation");
  (function () {
    var gap = 0;
    try { gap = native.sinceInstall(); } catch (e) { return; }
    var ttfb = Math.round(now() - t0);
    try {
      var nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.responseStart) ttfb = Math.round(nav.responseStart);
    } catch (e) {}
    try {
      native.log("gap before the overlay could exist: " + gap + "ms total = "
        + Math.max(0, gap - ttfb) + "ms before the request left + " + ttfb + "ms to first byte");
    } catch (e) {}
  })();

  /* 3. CRYSTAL - the station itself. Fifteen bytes; it times the LAN, not a
        payload, which is exactly what wants timing here. */
  (function () {
    var at = since();
    fetch("/healthz", { cache: "no-store" }).then(function (r) {
      var ms = since() - at;
      if (r.ok) {
        say("station <b>" + location.host + "</b> answered /healthz in " + ms + " ms");
        land("crystal");
      } else {
        say("station answered /healthz <b>" + r.status + "</b> after " + ms + " ms");
        land("crystal", false);
      }
    }).catch(function (err) {
      say("station did not answer /healthz: " + (err && err.message));
      land("crystal", false);
    });
  })();

  /* 4 / 5 / 7 / 8 / 9 - read off the PANEL'S OWN first /api/dj.
   *
   * /api/dj is 435 kB on this station. Asking for it a second time at boot
   * would double the one payload the whole panel is already waiting on, over
   * Wi-Fi, on a station documented as being starved by chatty clients. So
   * `fetch` is wrapped for as long as it takes the panel's own first poll to
   * land, the answer is read out of a clone, and the wrapper comes straight
   * back off. Nothing extra goes on the wire.
   */
  (function () {
    var real = win.fetch;
    if (typeof real !== "function") return;
    var restored = false;
    function restore() {
      if (restored) return;
      restored = true;
      if (win.fetch === wrapped) win.fetch = real;
    }
    function wrapped(input, init) {
      var url = "";
      try { url = typeof input === "string" ? input : (input && input.url) || ""; } catch (e) {}
      var isDj = url.indexOf("/api/dj") !== -1 && url.indexOf("/api/dj/") === -1;
      if (!isDj || djSeen) return real.apply(win, arguments);
      djSeen = true;
      var at = since();

      /* Did it carry the bearer? That IS the key-discovery fact - the
         terminal self-provisions its key off the panel, and the proof it
         worked is the header the panel actually sent. */
      var bearer = false;
      try {
        var h = (init && init.headers) || (input && input.headers) || null;
        if (h) {
          var v = typeof h.get === "function" ? h.get("Authorization")
            : (h.Authorization || h.authorization || "");
          bearer = !!v && String(v).indexOf("Bearer ") === 0 && String(v).length > 8;
        }
      } catch (e) {}
      say("panel asked <b>/api/dj</b> · api key " + (bearer ? "discovered, bearer sent" : "not sent"));
      land("tint", bearer);

      var out;
      try { out = real.apply(win, arguments); } catch (e) { restore(); throw e; }
      out.then(function (r) {
        restore();
        var ms = since() - at;
        if (!r || !r.ok) {
          say("/api/dj answered <b>" + (r && r.status) + "</b> after " + ms + " ms");
          land("grader", false); land("stores", false);
          land("schedule", false); land("air", false);
          return;
        }
        r.clone().text().then(function (body) { readDj(body, ms); })
          .catch(function () {
            land("grader", false); land("stores", false);
            land("schedule", false); land("air", false);
          });
      }).catch(function () {
        restore();
        say("/api/dj did not answer");
        land("grader", false); land("stores", false);
        land("schedule", false); land("air", false);
      });
      return out;
    }
    win.fetch = wrapped;
    /* Never leave the panel's fetch wrapped for longer than the sequence. */
    setTimeout(restore, CAP_MS + 500);

    /* Cheap readings off the raw text. The panel parses this payload itself;
       parsing 435 kB a second time on an MT6768 to print four numbers is not
       a trade worth making, so these are regexes over the body instead. */
    function pick(body, re, fallback) {
      var m = body.match(re);
      return m ? m[1] : fallback;
    }
    function unescapeJson(s) {
      try { return JSON.parse('"' + s + '"'); } catch (e) { return s; }
    }
    function readDj(body, ms) {
      var kb = Math.round(body.length / 1024);
      say("<b>/api/dj</b> answered " + kb + " kB in " + ms + " ms");
      land("grader");

      var ready = pick(body, /"ready":\s*(\d+)/, null);
      var target = pick(body, /"target":\s*(\d+)/, null);
      var clips = pick(body, /"pantry_clips":\s*(\d+)/, null);
      var mb = pick(body, /"pantry_mb":\s*([\d.]+)/, null);
      if (ready !== null) {
        say("cupboard <b>" + ready + "</b> rounds ready against a target of " + target
          + (clips ? (" · pantry " + clips + " clips, " + Math.round(+mb) + " MB") : ""));
        land("stores");
      } else { land("stores", false); }

      var on = /"on":\s*true/.test(body);
      var paused = /"paused":\s*true/.test(body);
      var music = pick(body, /"music_to":\s*"([^"]*)"/, "?");
      var voice = pick(body, /"voice_to":\s*"([^"]*)"/, "?");
      say("air <b>" + (on ? "ON" : "OFF") + "</b>" + (paused ? ", paused" : ", running")
        + " · music -> " + music + " · voice -> " + voice);
      land("schedule", on && !paused);

      var at2 = body.indexOf('"now"');
      var nowTitle = null, nowArtist = null;
      if (at2 !== -1) {
        var slab = body.slice(at2, at2 + 700);
        nowTitle = pick(slab, /"title":\s*"((?:[^"\\]|\\.)*)"/, null);
        nowArtist = pick(slab, /"artist":\s*"((?:[^"\\]|\\.)*)"/, null);
      }
      if (nowTitle) {
        say("on the air now: <b>" + unescapeJson(nowTitle).slice(0, 44) + "</b>"
          + (nowArtist ? (" - " + unescapeJson(nowArtist).slice(0, 26)) : ""));
        land("air");
      } else {
        say("nothing on the air this second");
        land("air", false);
      }
    }
  })();

  /* 6. RECORDING - which audio engine actually loaded.
   *
   * `window.pineSampler` is put up by the native shim at document start when
   * Oboe attached, and by sampler-engine.js (Web Audio) otherwise - and that
   * second one only lands at onPageFinished. So this is polled rather than
   * read once, and it reports what is TRUE by the cap rather than guessing. */
  (function () {
    var tries = 0;
    var probe = setInterval(function () {
      tries += 1;
      var s = win.pineSampler;
      if (s && s.backend) {
        clearInterval(probe);
        var isNative = String(s.backend).toLowerCase().indexOf("oboe") !== -1;
        say("audio engine: <b>" + s.backend + "</b>"
          + (isNative ? " - native, exclusive low latency" : " - browser fallback"));
        land("recording", isNative);
      } else if (tries > 22 || finished) {
        clearInterval(probe);
        say("audio engine: not up yet");
        land("recording", false);
      }
    }, 110);
  })();

  /* 10. LEARNING - the panel document itself. */
  (function () {
    function done() {
      if (panelReady) return;
      panelReady = true;
      var nodes = 0;
      try { nodes = document.getElementsByTagName("*").length; } catch (e) {}
      var kb = 0;
      try {
        var nav = performance.getEntriesByType("navigation")[0];
        kb = Math.round(((nav && (nav.decodedBodySize || nav.transferSize)) || 0) / 1024);
      } catch (e) {}
      say("panel document ready · " + nodes + " nodes"
        + (kb ? (" · " + kb + " kB of html") : ""));
      land("learning");
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", done);
    else done();
  })();


  /* --------------------------------------------------------------------- */
  /* 2. WRITING - the geometry engine, and the scene it makes possible       */
  /* --------------------------------------------------------------------- */

  /* The engine source is KEPT, not discarded after evaluation: the scene may
     want to hand it to a worker, and asking the native side for 593 kB twice
     is 593 kB of pointless copying. Released as soon as the scene is up. */
  var threeSource = null;

  /* The engine is asked for on the frame AFTER the console has painted, so
     the screen is never blank waiting on a 593 kB parse. */
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      if (finished) return;
      var at = since();
      var bytes = 0;
      try { bytes = native.threeBytes(); } catch (e) {}
      try { threeSource = native.three() || null; } catch (e) { threeSource = null; }
      if (win.THREE) {
        say("geometry engine already resident · three r" + win.THREE.REVISION);
        land("writing");
        build();
        return;
      }
      if (!threeSource) {
        /* Honest, and survivable: the console alone is still a boot screen,
           and the drain clock ends the sequence whether or not this works. */
        say("geometry engine unavailable · running the console alone");
        land("writing", false);
        return;
      }
      try {
        /* Indirect eval, so three's UMD wrapper runs in global scope and
           defines window.THREE exactly as a <script> would. No network, no
           script tag, no file:// scheme for an http:// page to refuse. */
        (0, eval)(threeSource);
      } catch (err) {
        say("geometry engine would not load: " + (err && err.message));
        land("writing", false);
        return;
      }
      say("geometry engine <b>three r" + (win.THREE ? win.THREE.REVISION : "?") + "</b> · "
        + Math.round(bytes / 1024) + " kB off the apk, no network · " + (since() - at) + " ms");
      land("writing");
      build();
    });
  });

  /* --------------------------------------------------------------------- */
  /* THE SCENE, AND WHY IT IS NOT ON THE MAIN THREAD                        */
  /* --------------------------------------------------------------------- */

  /* This was the hardest measurement of the whole job, and it changed the
   * design.
   *
   * The first working build drew the ten stations on the page's own canvas
   * with requestAnimationFrame, which is how every other 3js view in this
   * project works. On the tablet it produced TWO FRAMES in the 1.33 seconds
   * the overlay was on screen, and not one block ever appeared. The console
   * text was equally frozen: the frame that was on screen at 4.1 s showed
   * the state of the console at 254 ms.
   *
   * The cause is not the scene, which is ten boxes. It is that the panel is
   * a 2.1 MB document whose own boot scripts take the ONE main thread from
   * the moment rendering unblocks - which is precisely the window the boot
   * sequence occupies. Timers and promises still ran in the gaps between the
   * panel's tasks (the console lines are logged at their true times), but
   * the gaps were never long enough for a rendering opportunity. No amount
   * of making the scene cheaper helps: it was never given a frame.
   *
   * So the scene runs on a WORKER against an OffscreenCanvas. A worker has
   * its own thread and its own timers, and an OffscreenCanvas transferred to
   * it pushes frames to the compositor without the main thread's
   * involvement. The console text still freezes with the page - it is DOM -
   * but it is timestamped, so it catches up honestly, and the motion the
   * operator actually watches is immune.
   *
   * The scene is written ONCE, as a self-contained function, and is either
   * serialised into the worker with Function.prototype.toString() or called
   * directly on the main thread when the WebView has no OffscreenCanvas.
   * That is why it takes everything through `env` and closes over nothing:
   * a single reference to an outer variable would compile fine here and
   * throw in the worker, where the outer scope does not exist.
   */
  function PINE_SCENE(env) {
    var THREE = env.THREE;
    var stages = env.stages;
    var SWAY = env.sway;

    /* A canvas for a label. `document` does not exist in a worker, so the
       2D surface has to be asked for by the right name in each world. */
    function makeCanvas(w, h) {
      if (typeof document !== "undefined" && document.createElement) {
        var c = document.createElement("canvas");
        c.width = w; c.height = h;
        return c;
      }
      return new OffscreenCanvas(w, h);
    }

    var renderer = new THREE.WebGLRenderer({
      canvas: env.canvas, antialias: false, alpha: false, powerPreference: "low-power"
    });
    /* antialias off and the pixel ratio pinned to 1.5: this is an MT6768
       drawing ten boxes for two seconds, not a game. */
    renderer.setPixelRatio(Math.min(env.dpr || 1, 1.5));

    var scene = new THREE.Scene();
    scene.background = new THREE.Color(0x03060b);
    scene.fog = new THREE.Fog(0x03060b, 60, 200);
    var camera = new THREE.PerspectiveCamera(42, 1.6, 1, 600);
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    var sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(10, 22, 30);
    scene.add(sun);

    var group = new THREE.Group();
    scene.add(group);

    /* ONE box, ONE sphere, shared by everything. Ten separate geometries
       would be ten buffer uploads for ten identical cubes. Every geometry,
       material and texture made here is also pushed onto `owned`, because
       scene.traverse() at teardown would visit the shared ones ten times
       and miss the pooled ones that are hidden. */
    var boxGeo = new THREE.BoxGeometry(5.4, 2, 5.4);
    var ballGeo = new THREE.SphereGeometry(0.42, 10, 8);
    var linkMat = new THREE.LineBasicMaterial({ color: 0x22304a, transparent: true, opacity: 0.9 });
    var owned = { geometries: [boxGeo, ballGeo], materials: [linkMat], textures: [] };

    function label(text, color) {
      var px = 40;
      var c = makeCanvas(8, 8);
      var x = c.getContext("2d");
      x.font = "700 " + px + "px ui-monospace, monospace";
      c.width = Math.ceil(x.measureText(text).width) + 20;
      c.height = px + 18;
      x = c.getContext("2d");
      x.font = "700 " + px + "px ui-monospace, monospace";
      x.fillStyle = color;
      x.textBaseline = "middle";
      x.fillText(text, 10, c.height / 2);
      var tex = new THREE.CanvasTexture(c);
      var mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, opacity: 0 });
      var sp = new THREE.Sprite(mat);
      sp.scale.set(1.2 * (c.width / c.height), 1.2, 1);
      sp.frustumCulled = false;
      owned.materials.push(mat);
      owned.textures.push(tex);
      return sp;
    }

    /* One row of ten on the same 9-unit pitch the panel's own RapAssembly
       view uses, so the two read as the same drawing of the same line. */
    function slotOf(i) { return { x: -40.5 + i * 9, y: 0 }; }

    var blocks = stages.map(function (s, i) {
      var slot = slotOf(i);
      var mat = new THREE.MeshStandardMaterial({
        color: 0x1a2438,
        emissive: new THREE.Color(s.color),
        emissiveIntensity: 0.03,
        roughness: 0.5,
        metalness: 0.2
      });
      owned.materials.push(mat);
      var mesh = new THREE.Mesh(boxGeo, mat);
      mesh.frustumCulled = false;
      mesh.visible = false;
      var face = label(s.face, "rgba(214,232,255,.95)");
      face.position.set(slot.x, slot.y - 3.1, 0);
      group.add(mesh);
      group.add(face);

      /* Where it flies in FROM. Deterministic per index rather than random,
         so the sequence looks the same every launch - a splash that shuffles
         itself reads as noise. */
      var side = (i % 2) ? 1 : -1;
      var far = new THREE.Vector3(
        slot.x + side * (48 + (i % 3) * 14),
        slot.y + ((i % 4) - 1.5) * 30,
        -74 + (i % 5) * 10
      );
      var rot0 = new THREE.Euler(side * 1.2, i * 0.7, side * 0.65);
      mesh.position.copy(far);
      mesh.scale.setScalar(0.01);
      mesh.rotation.copy(rot0);

      return {
        lit: !!s.lit, mesh: mesh, face: face, mat: mat, slot: slot,
        far: far, home: new THREE.Vector3(slot.x, slot.y, 0), rot0: rot0,
        t: -1, wait: 0, done: false
      };
    });

    /* The connectors, one per hand-off, each drawn only once BOTH its ends
       have arrived - the line IS the hand-off, and a hand-off out of an empty
       slot would be a lie. Two fixed points mutated in place, never
       reallocated, and never frustum-culled (a two-point line's bounding
       sphere is a pinhole and Chromium will happily cull it). */
    var links = [];
    for (var li = 0; li < blocks.length - 1; li += 1) {
      var geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
      owned.geometries.push(geo);
      var line = new THREE.Line(geo, linkMat);
      line.visible = false;
      line.frustumCulled = false;
      group.add(line);
      links.push({ geo: geo, line: line, from: blocks[li], to: blocks[li + 1], t: -1 });
    }

    /* A small pool of packets. Three materials, one geometry, never grown. */
    var packetMats = [0x4bb3ff, 0x2ee08a, 0xffd479].map(function (hex) {
      var m = new THREE.MeshBasicMaterial({ color: hex });
      owned.materials.push(m);
      return m;
    });
    var packets = [];
    for (var pi = 0; pi < 6; pi += 1) {
      var pm = new THREE.Mesh(ballGeo, packetMats[pi % 3]);
      pm.visible = false;
      pm.frustumCulled = false;
      group.add(pm);
      packets.push({ mesh: pm, t: 1, a: null, b: null });
    }
    var packetAt = 0;
    function sendPacket(a, b, which) {
      var q = packets[packetAt % packets.length];
      packetAt += 1;
      q.mesh.material = packetMats[which % packetMats.length];
      q.a = a; q.b = b; q.t = 0;
      q.mesh.visible = true;
    }

    var W = env.width || 1000, H = env.height || 600;
    function fit(w, h) {
      W = w || W; H = h || H;
      renderer.setSize(W, H, false);
      camera.aspect = W / H;
      /* 47 and not 43.2 (the line's true half width plus half a block): the
         group sways +/- SWAY radians about its own Y, which swings the end
         blocks towards the camera and therefore outwards on screen. Fitting
         the still line exactly is what clipped IDEATION off the left edge on
         the real tablet. */
      var half = Math.tan(camera.fov * Math.PI / 360);
      var dist = Math.max(34, 47 / camera.aspect / half, 14 / half);
      camera.position.set(0, dist * 0.13, dist);
      /* Aimed BELOW the line, which lifts the line up the screen - the lower
         fifth belongs to the console and the type must not sit on the boxes. */
      camera.lookAt(0, -2.0, 0);
      camera.updateProjectionMatrix();
      scene.fog.near = dist + 14;
      scene.fog.far = dist + 110;
    }
    fit(W, H);

    function easeOut(u) { return 1 - Math.pow(1 - u, 3); }

    function arrive(index, delay, lit) {
      var b = blocks[index];
      if (!b || b.t >= 0) return;
      if (lit !== undefined) b.lit = !!lit;
      b.wait = delay || 0;
      b.t = 0;
      b.mesh.visible = true;
    }

    /* THE CLOCK, and it must be requestAnimationFrame wherever there is one.
       A worker timer looked like the better idea - its own thread, its own
       clock, nothing the panel can starve - and it rendered perfectly and put
       NOTHING on screen. Chromium pushes an OffscreenCanvas's WebGL frame to
       its placeholder at the end of an ANIMATION FRAME, not at the end of any
       old task, so a setTimeout loop draws into a buffer nobody ever reads.
       Measured: the worker reported a 1250x747 canvas with eight blocks in
       flight while the screen showed an empty rectangle. */
    var hasRaf = (typeof requestAnimationFrame === "function");
    var schedule = hasRaf
      ? function (cb) { return requestAnimationFrame(cb); }
      : function (cb) { return setTimeout(function () { cb(performance.now()); }, 16); };
    var unschedule = hasRaf
      ? function (h) { cancelAnimationFrame(h); }
      : function (h) { clearTimeout(h); };

    var alive = true;
    var handle = 0;
    var last = 0;
    var frames = 0;
    var report = env.report || function () {};

    function tick(ms) {
      if (!alive) return;
      frames += 1;
      /* A heartbeat, because a worker that dies is otherwise perfectly
         silent: the canvas keeps whatever it last drew and the page has no
         way to tell that apart from a scene with nothing on it yet. */
      if (frames === 1 || frames === 10 || frames === 30) {
        var seen = 0;
        blocks.forEach(function (b) { if (b.t >= 0) seen += 1; });
        report("beat " + frames + " at " + Math.round(ms) + "ms · "
          + (hasRaf ? "raf" : "timer") + " · canvas " + env.canvas.width + "x"
          + env.canvas.height + " · " + seen + " blocks in flight or landed");
      }
      /* The cap is 250 ms and NOT the usual 50. Even on a worker this can be
         descheduled; a frame that arrives late must advance the world by how
         long it really was, or the blocks crawl and the line never finishes. */
      var dt = last ? Math.min(0.25, (ms - last) / 1000) : 0.016;
      last = ms;

      blocks.forEach(function (b, i) {
        if (b.t < 0) return;
        if (b.wait > 0) { b.wait -= dt; return; }
        if (b.t < 1) {
          b.t = Math.min(1, b.t + dt / 0.32);
          var u = easeOut(b.t);
          b.mesh.position.lerpVectors(b.far, b.home, u);
          b.mesh.scale.setScalar(0.01 + 0.99 * u);
          b.mesh.rotation.set(b.rot0.x * (1 - u), b.rot0.y * (1 - u), b.rot0.z * (1 - u));
          b.face.material.opacity = Math.max(0, (u - 0.55) / 0.45);
          b.mat.emissiveIntensity = 0.03 + u * (b.lit ? 0.24 : 0.05);
          if (b.t >= 1 && !b.done) {
            b.done = true;
            b.mesh.rotation.set(0, 0, 0);
            /* The hand-offs this arrival completes. */
            [i - 1, i].forEach(function (k) {
              var link = links[k];
              if (!link || link.t >= 0) return;
              if (!link.from.done || !link.to.done) return;
              link.t = 0;
              link.line.visible = true;
              sendPacket(link.from.slot, link.to.slot, k % 3);
            });
          }
        } else {
          /* A landed block breathes on its stage colour, so the line reads as
             running rather than parked. A dim block stays dim: it is a fact
             that did not hold. */
          b.mat.emissiveIntensity = b.lit ? (0.22 + 0.07 * Math.sin(ms / 420 + i)) : 0.05;
          b.mesh.position.z = Math.sin(ms / 900 + i) * 0.16;
        }
      });

      links.forEach(function (k) {
        if (k.t < 0 || k.t >= 1) return;
        k.t = Math.min(1, k.t + dt / 0.20);
        var u = easeOut(k.t);
        var ax = k.from.slot.x + 2.75, bx = k.to.slot.x - 2.75;
        var arr = k.geo.attributes.position.array;
        arr[0] = ax; arr[1] = 0; arr[2] = 0;
        arr[3] = ax + (bx - ax) * u; arr[4] = 0; arr[5] = 0;
        k.geo.attributes.position.needsUpdate = true;
      });

      packets.forEach(function (q) {
        if (q.t >= 1) { if (q.mesh.visible) q.mesh.visible = false; return; }
        q.t = Math.min(1, q.t + dt / 0.38);
        q.mesh.position.set(
          q.a.x + (q.b.x - q.a.x) * q.t,
          0.9 + Math.sin(q.t * Math.PI) * 0.7,
          1.2
        );
      });

      /* A slow drift, so the scene is alive without asking for a gesture. */
      group.rotation.y = Math.sin(ms / 2600) * SWAY;
      group.rotation.x = -0.06 + Math.sin(ms / 3900) * 0.02;

      try {
        renderer.render(scene, camera);
      } catch (err) {
        /* A throw here used to stop the loop dead and leave a blank canvas
           that looked exactly like a scene with nothing on it yet. */
        report("render threw: " + (err && err.message));
        alive = false;
        return;
      }
      handle = schedule(tick);
    }
    handle = schedule(tick);

    /* TEARDOWN - the part a memory-constrained device actually cares about.
       Everything this scene made, by hand: traverse() would visit the shared
       geometries ten times and miss the pooled ones that are hidden. */
    function dispose() {
      if (!alive) return;
      alive = false;
      try { unschedule(handle); } catch (e) {}
      try { owned.geometries.forEach(function (g) { g.dispose(); }); } catch (e) {}
      try { owned.textures.forEach(function (t) { t.dispose(); }); } catch (e) {}
      try { owned.materials.forEach(function (m) { m.dispose(); }); } catch (e) {}
      try { scene.clear(); } catch (e) {}
      try { renderer.dispose(); } catch (e) {}
      /* THE ONE THAT MATTERS ON THIS TABLET. dispose() releases three's own
         objects; only forceContextLoss() hands the GL context itself back,
         and this WebView process has been killed for less. */
      try { renderer.forceContextLoss(); } catch (e) {}
    }

    return { arrive: arrive, resize: fit, dispose: dispose };
  }

  /* --------------------------------------------------------------------- */
  /* Standing the scene up                                                  */
  /* --------------------------------------------------------------------- */

  /* WHAT WAS TRIED HERE AND MEASURED NOT TO WORK, because the next person
   * will have the same idea and it is a good one.
   *
   * The scene was moved onto a Worker with an OffscreenCanvas, to take it off
   * the main thread the panel is monopolising. It worked on the worker side
   * perfectly: the worker reported `three r147 on an OffscreenCanvas`, a
   * 1250x747 drawing surface and ten blocks landed - and the screen showed an
   * empty rectangle, in three runs out of four. The frames were rendered and
   * never composited to the placeholder canvas. Both loops were tried; a
   * setTimeout loop renders and never pushes (Chromium pushes a WebGL
   * OffscreenCanvas frame at the end of an animation frame, not at the end of
   * any task), and a requestAnimationFrame loop pushed intermittently, which
   * is worse than not at all because it looks like it works.
   *
   * A/B on the real tablet, four launches each: the main-thread scene drew
   * the assembly in every run that got any frames at all; the worker scene
   * drew it in one. So the scene stays on the page's own thread, where it is
   * choppy (about eight frames a second while the panel boots) and RELIABLE.
   * The animation is written to be told how long a frame really took - see
   * the 250 ms dt cap - so eight frames still finish the line.
   */
  function build() {
    if (!win.THREE || finished || scene3) return;

    var canvas = document.createElement("canvas");
    canvas.style.touchAction = "none";
    root.insertBefore(canvas, chrome);

    var w = root.clientWidth || win.innerWidth || 1000;
    var h = root.clientHeight || win.innerHeight || 600;
    var dpr = Math.min(win.devicePixelRatio || 1, 1.5);
    /* The stage table the scene needs, and nothing else. */
    var plain = STAGES.map(function (s) { return { face: s.face, color: s.color, lit: false }; });

    startOnMainThread(canvas, w, h, dpr, plain);
  }
  function startOnMainThread(canvas, w, h, dpr, plain) {
    var made;
    try {
      made = PINE_SCENE({
        THREE: win.THREE, canvas: canvas, width: w, height: h, dpr: dpr,
        stages: plain, sway: SWAY,
        report: function (text) { try { native.log("scene: " + text); } catch (e) {} }
      });
    } catch (err) {
      say("no webgl context: " + (err && err.message));
      try { canvas.parentNode.removeChild(canvas); } catch (e) {}
      return;
    }
    try { native.log("scene on the main thread (no OffscreenCanvas here)"); } catch (e) {}
    var resize = function () {
      made.resize(root.clientWidth || win.innerWidth || w, root.clientHeight || win.innerHeight || h);
    };
    win.addEventListener("resize", resize);
    scene3 = {
      worker: false, canvas: canvas, url: null, resize: resize,
      arrive: function (stage, delay) { made.arrive(INDEX[stage.key], delay || 0, !!stage.lit); },
      close: function () { made.dispose(); }
    };
    replayReleased();
    threeSource = null;
    try { native.done(); } catch (e) {}
  }

  /* Stages the drain let go of before the scene existed are still owed their
     arrival. They cascade rather than appearing together, because ten boxes
     materialising on one frame reads as a glitch and not an assembly. */
  function replayReleased() {
    released.forEach(function (s, i) { scene3.arrive(s, i * 0.06); });
  }

  function dispose() {
    var v = scene3;
    scene3 = null;
    if (!v) return;
    try { win.removeEventListener("resize", v.resize); } catch (e) {}
    try { v.close(); } catch (e) {}
    /* The canvas element goes whether or not the context came back cleanly.
       A transferred canvas cannot be resized from here, so it is only
       detached; the worker's forceContextLoss is what releases the GL side. */
    if (!v.worker) { try { v.canvas.width = 1; v.canvas.height = 1; } catch (e) {} }
    try { v.canvas.parentNode.removeChild(v.canvas); } catch (e) {}
  }

  /* --------------------------------------------------------------------- */
  /* PHASE 2 - the panel arriving                                           */
  /* --------------------------------------------------------------------- */

  function slideIn() {
    var reduced = false;
    try {
      reduced = !!(win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (e) {}
    if (reduced) { try { native.log("phase 2 skipped: reduced motion"); } catch (e) {} return; }
    /* No costume on a half-built house: if the document is still parsing,
       body.children is not yet the panel's sections and animating them would
       animate a fragment. */
    if (document.readyState === "loading" || !document.body) {
      try { native.log("phase 2 skipped: document still parsing"); } catch (e) {}
      return;
    }

    var picks = [];
    var kids = document.body.children;
    for (var i = 0; i < kids.length && picks.length < SLIDE_MOST; i += 1) {
      var el = kids[i];
      var tag = el.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "LINK" || tag === "TEMPLATE") continue;
      if (el === root || el.id === "pine-boot" || el.id === "sampler"
        || el.id === "pineSamplerTab") continue;
      var box;
      try { box = el.getBoundingClientRect(); } catch (e) { continue; }
      if (box.height < 24 || box.width < 60) continue;
      var cs = win.getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      /* A FIXED element is already outside the flow and is almost always a
         drawer, a toast or a scene host; sliding it reads as a bug rather
         than a flourish - and it is the one shape most likely to hold
         `position: fixed` children that a transform would break. */
      if (cs.position === "fixed") continue;
      picks.push(el);
    }
    if (!picks.length) {
      try { native.log("phase 2 skipped: no top-level sections to move"); } catch (e) {}
      return;
    }

    var html = document.documentElement;
    html.classList.add("pine-boot-sliding");

    /* The WHOLE style attribute is captured and put back, not just the
       properties touched. That is what guarantees nothing is left with a
       stale `transform` - and a stale transform on a section turns every
       `position: fixed` inside it into `position: absolute`, which is a
       quiet, permanent bug for the price of a 300 ms flourish. */
    var kept = picks.map(function (el) { return el.getAttribute("style"); });

    picks.forEach(function (el, i) {
      var dx = (i % 2 ? 1 : -1) * Math.round((win.innerWidth || 1000) * 0.6);
      el.style.transform = "translate3d(" + dx + "px,0,0)";
      el.style.opacity = "0";
      el.style.willChange = "transform,opacity";
    });
    /* One reflow for the whole batch, so every element starts from its
       off-screen position instead of transitioning from nothing. */
    void document.body.offsetWidth;

    picks.forEach(function (el, i) {
      var delay = i * SLIDE_STEP_MS;
      el.style.transition = "transform " + SLIDE_MS + "ms cubic-bezier(.22,.9,.26,1) "
        + delay + "ms, opacity " + Math.round(SLIDE_MS * 0.7) + "ms linear " + delay + "ms";
      el.style.transform = "translate3d(0,0,0)";
      el.style.opacity = "1";
    });

    var total = (picks.length - 1) * SLIDE_STEP_MS + SLIDE_MS;
    var what = picks.map(function (el) {
      return (el.tagName + (el.id ? "#" + el.id : "")
        + (el.className && typeof el.className === "string"
          ? "." + el.className.trim().split(/\s+/).join(".") : "")).slice(0, 40);
    }).join(", ");
    try { native.log("phase 2: " + picks.length + " sections over " + total + "ms -> " + what); } catch (e) {}

    setTimeout(function () {
      picks.forEach(function (el, i) {
        if (kept[i] === null) el.removeAttribute("style");
        else el.setAttribute("style", kept[i]);
      });
      html.classList.remove("pine-boot-sliding");
      try { native.log("phase 2 done, every transform cleared"); } catch (e) {}
    }, total + 80);
  }

  /* --------------------------------------------------------------------- */
  /* When the sequence ends                                                 */
  /* --------------------------------------------------------------------- */

  function finish(why) {
    if (finished) return;
    finished = true;
    try { native.log("handover at " + since() + "ms (" + why + ")"); } catch (e) {}
    /* Phase 2 starts WITH the fade, not after it - the panel should be
       arriving as the scene leaves, not queued behind it. */
    slideIn();
    root.classList.add("pine-boot-out");
    /* The scene is disposed the moment it stops being looked at; the fade is
       a 240 ms opacity transition on a div and needs no WebGL context. */
    dispose();
    setTimeout(function () {
      try { root.parentNode.removeChild(root); } catch (e) {}
      try { style.parentNode.removeChild(style); } catch (e) {}
      try { native.done(); } catch (e) {}
    }, 300);
  }

  /* THE DURATION FOLLOWS REAL READINESS, WITH A HARD CAP.
   *
   * Ready means: the panel's document is up, every stage that was going to
   * land has landed, and the release queue has drained. Past the floor, that
   * is the moment to leave. The cap is not a target - it is the promise that
   * a slow or absent station costs the operator four seconds and not a
   * launch. Note that nothing here waits on the SCENE: a tablet that never
   * got a WebGL context still finishes on exactly this clock. */
  (function () {
    var watch = setInterval(function () {
      if (finished) { clearInterval(watch); return; }
      var ms = since();
      var seen = sincePaint();

      /* THE CEILING, in two parts.
       *
       * CAP_MS is the promise: four seconds after the document starts, the
       * app matters more than the sequence. But if the panel blocked
       * rendering for most of that - which this one does, 2.18 MB with no
       * content-encoding - the cap would fire on a scene the operator had
       * watched for 300 ms, which is a flicker and reads as a fault. So the
       * cap yields just far enough to let the floor be met on screen, and
       * HARD_CAP_MS is the line that yields to nothing. */
      var cap = CAP_MS;
      if (paintedAt !== null && seen < FLOOR_MS) {
        cap = Math.min(HARD_CAP_MS, ms + (FLOOR_MS - seen) + 120);
      }
      if (ms >= cap || ms >= HARD_CAP_MS) { clearInterval(watch); finish("cap"); return; }

      /* Ready: the panel's document is up, every fact that was going to land
         has landed and been released, and the scene has had its floor ON
         SCREEN rather than merely in memory.
         
         And then the GRACE, which is the answer to a measurement. Waiting for
         all ten facts pushed the handover to first paint + 3.5 s on a run
         where /api/dj took its time, and every millisecond past the floor is
         a millisecond the panel was ready and hidden. So once the document is
         up and the floor is served, the stragglers get half a second and no
         more; the line hands over part-built, which is the truth about a
         station that had not answered yet. */
      if (seen >= FLOOR_MS && panelReady) {
        var complete = !queue.length && landedCount >= STAGES.length;
        if (complete) { clearInterval(watch); finish("ready"); return; }
        if (seen >= FLOOR_MS + GRACE_MS) {
          clearInterval(watch);
          finish("grace · " + landedCount + "/" + STAGES.length + " landed");
        }
      }
    }, 50);
  })();
})(typeof window !== "undefined" ? window : globalThis);
