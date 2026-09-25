/* The Sampler, standing up inside the station panel on the tablet.
 *
 * The sampler was written for the Pine Box desktop and needs nothing
 * Electron-specific: `window.pineDesktop` (the tablet's bridge carries all
 * 47 methods), a feed model, and `window.pineSampler`. Proved on the real
 * device before this file existed - injected live, it mounted and drew 16
 * pads, 5 banks and 240 feed rows.
 *
 * This file does NOT load the sampler's scripts. It cannot: the page is an
 * http:// origin and the assets live at file:///android_asset/, so a
 * <script src> pointing at them is refused. The Kotlin side reads every
 * asset and evaluates it, and calls the two functions here around that -
 * scaffold() before, ready() after.
 *
 * Two things had to be learned on the device, and both are handled:
 *
 * 1. THE CLASS COLLISION. The desktop marks the sampler `class="view
 *    pb-sampler"` because Electron's switcher owns `.view` and toggles
 *    `.active` on it. The STATION PANEL also owns `.view`, and its own
 *    switcher turned the sampler straight back off. Here the host wears its
 *    own class and never `.view`.
 *
 * 2. THE BOOTSTRAP ORDER. `sampler.js` binds to `#samplerTabBtn` and
 *    `#sampler` the moment it loads. If those do not exist yet the listener
 *    is never attached and nothing mounts, however many times you click. So
 *    the host is built FIRST and mounted explicitly.
 */
(function (root) {
  "use strict";

  var HOST_ID = "sampler";          /* what sampler.js looks for */
  var TAB_ID = "samplerTabBtn";

  /* sampler.css keys its layout off `.view.pb-sampler.active`, which can
   * never match here. This restates only that layout rule against the
   * standalone host; every other rule in the stylesheet is keyed off .pb-*
   * classes and applies unchanged. */
  var STANDALONE_CSS = [
    "#" + HOST_ID + "{position:fixed;inset:0;z-index:2147483000;",
    "background:#101419;color:#edf3f5;display:none;",
    /* Must agree with sampler.css - this string is what the tablet host
   actually gets, and a bare 1fr will not shrink below its content. */
    "grid-template-columns:minmax(240px,30%) minmax(0,1fr);gap:14px;padding:14px;",
    "overflow:hidden;font-family:Inter,Segoe UI,system-ui,sans-serif}",
    "#" + HOST_ID + ".open{display:grid}",
    /* The handle sits on the RIGHT edge on purpose: the left edge belongs
     * to the app's own drawer, and two things fighting for one edge is
     * worse than either alone. */
    "#pineSamplerTab{position:fixed;right:0;top:50%;transform:translateY(-50%);",
    "z-index:2147483001;background:#1c242c;color:#edf3f5;",
    "border:1px solid #35414c;border-right:none;border-radius:10px 0 0 10px;",
    "padding:16px 9px;font-size:12px;letter-spacing:.09em;writing-mode:vertical-rl;",
    "cursor:pointer;touch-action:manipulation}",
    "#pineSamplerTab.on{background:#65c7da;color:#05131a;border-color:#65c7da}",
    /* Portrait: the feed goes above the pads rather than beside them, so
     * the grid keeps room to be hit with a thumb. */
    "@media (max-width:900px){#" + HOST_ID + ".open{",
    "grid-template-columns:1fr;grid-template-rows:minmax(110px,24%) 1fr}}"
  ].join("");

  function make(tag, id) {
    var node = document.createElement(tag);
    if (id) node.id = id;
    return node;
  }

  /* Called BEFORE the sampler's own scripts are evaluated. */
  root.__pineSamplerScaffold = function () {
    if (document.getElementById(HOST_ID)) return "already";

    var style = make("style");
    style.textContent = (root.__pineSamplerCss || "") + STANDALONE_CSS;
    document.head.appendChild(style);

    var host = make("section", HOST_ID);
    host.className = "pb-sampler";
    document.body.appendChild(host);

    var hidden = make("button", TAB_ID);
    hidden.style.display = "none";
    document.body.appendChild(hidden);

    var handle = make("button", "pineSamplerTab");
    handle.textContent = "SAMPLER";
    handle.addEventListener("click", function () {
      var open = host.classList.toggle("open");
      handle.classList.toggle("on", open);
      /* The pads are sized by the grid, so they only get real geometry
       * once the host is actually visible. */
      if (open && root.PineSampler) root.PineSampler.repaint();
    });
    document.body.appendChild(handle);
    return "scaffolded";
  };

  /* Called AFTER every sampler script has been evaluated. */
  root.__pineSamplerReady = function () {
    var host = document.getElementById(HOST_ID);
    if (!host) return "no host";
    if (!root.PineSampler) return "sampler did not load";
    if (root.PineSampler.isMounted()) return "already mounted";
    root.PineSampler.mount(host).then(function () {
      if (root.console) {
        console.log("[pine] sampler ready; engine="
          + (root.pineSampler && root.pineSampler.backend));
      }
    }).catch(function (error) {
      if (root.console) console.error("[pine] sampler mount failed:", error);
    });
    return "mounting";
  };
})(typeof window !== "undefined" ? window : globalThis);
