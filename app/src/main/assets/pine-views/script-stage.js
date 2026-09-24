/* window.PineScriptStage - one line's lineage as the RapAssembly stage.
 *
 * THE SCENE GRAMMAR IS BORROWED, THE DATA IS NOT. /api/rapassembly is a
 * whole-station throughput dashboard with no line identity anywhere in it
 * (app.py:129825+), so none of its numbers appear here. What is reused is
 * the thing that is actually worth reusing: the canvas-plate-and-connector
 * pattern the Phone view proved (app.py:172423 phonePlate / 172502
 * phonePanel) - a 512x288 canvas drawn with real 2D type and hung on a
 * PlaneGeometry, joined by thin lines with a light travelling them. Type
 * drawn into a canvas texture stays crisp; type drawn as three.js geometry
 * or sprites does not, and this stage is nothing but type.
 *
 * TWO THINGS ARE DELIBERATELY DIFFERENT FROM THE DESKTOP'S 3JS PANELS.
 *
 * 1. THE CAMERA IS FITTED, NOT PLACED. Every existing panel hard-codes
 *    `camera.position.set(0, 0.6, 15.5)` against a wide desktop stage -
 *    the RapAssembly line spans roughly +/-43 units. On a 9" tablet in
 *    landscape (about 1000x600 CSS px) a fixed camera puts half the line
 *    off the edge, and the operator has no way to know something is
 *    missing. fitCamera() below measures the plates and solves for a
 *    distance that contains them in BOTH axes, so the same scene is whole
 *    on the tablet and on a 32" monitor.
 *
 * 2. THERE IS NO TIMER. Every 3js panel in renderer.js and app.py polls
 *    its endpoint on a setInterval - the Phone view every 2.5 s, the
 *    RapAssembly view likewise. This stage draws ONE line that has already
 *    happened and cannot change, so it polls nothing at all. The station
 *    has a documented history of being starved by chatty clients; a view
 *    that adds a second poller for a still picture would be indefensible.
 *    The only loop here is requestAnimationFrame, and it stops when the
 *    stage closes or the tab is hidden.
 *
 * three.js is VENDORED (the agent serves it at /vendor/three.min.js, 608
 * kB) and there is no CDN on this network. preload() starts that fetch
 * when the Script view mounts, so pressing 3D shows a scene rather than a
 * download.
 */
(function (root) {
  "use strict";

  const PLATE_W = 3.5;
  const PLATE_H = 1.97;
  const CANVAS_W = 512;             /* 512/288 = 1.778 = 3.5/1.97 */
  const CANVAS_H = 288;
  const COLUMNS = 5;                /* ten stations, serpentine, two rows */
  const GAP_X = 4.2;
  const GAP_Y = 2.65;

  const INK = {
    lit: {face: "#0d1a24", edge: "#4ec9c9", title: "#dff6ff", body: "#a9c4dc",
          chip: "#4ec9c9", chipInk: "#04070b"},
    dark: {face: "#0a1017", edge: "#22304a", title: "#7f92a6", body: "#5d6f82",
           chip: "#3d5a7a", chipInk: "#04070b"},
    /* Amber is the station's own colour for "we do not know", used for the
     * three stations the live route cannot fill. It must not read as an
     * error - nothing has failed - but it must not read as empty either. */
    pending: {face: "#161207", edge: "#e3be63", title: "#e3be63",
              body: "#a08b4f", chip: "#e3be63", chipInk: "#1a1405"}
  };

  let threeLoad = null;
  let live = null;

  /* ---------------------------------------------------------- three.js */

  function preload(baseUrl) {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = String(baseUrl || "").replace(/\/+$/, "") + "/vendor/three.min.js";
      tag.onload = () => resolve(root.THREE);
      tag.onerror = () => {
        threeLoad = null;
        reject(new Error("three.js did not load - the agent serves it at "
          + "/vendor/three.min.js, so this usually means the station is "
          + "unreachable rather than missing."));
      };
      document.head.appendChild(tag);
    });
    return threeLoad;
  }

  /* -------------------------------------------------------------- plate */

  /* Wrapping is done here rather than clipping, because a station's head
   * is often the one sentence that answers the question - "prepared ahead
   * - served off the shelf" clipped at 26 characters says nothing. */
  function wrap(ctx, body, width, most) {
    const words = String(body || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    for (const word of words) {
      const next = line ? line + " " + word : word;
      if (ctx.measureText(next).width > width && line) {
        lines.push(line);
        line = word;
        if (lines.length >= most) break;
      } else {
        line = next;
      }
    }
    if (line && lines.length < most) lines.push(line);
    return lines;
  }

  function roundedBox(ctx, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(r, 2); ctx.lineTo(w - r, 2);
    ctx.quadraticCurveTo(w - 2, 2, w - 2, r);
    ctx.lineTo(w - 2, h - r);
    ctx.quadraticCurveTo(w - 2, h - 2, w - r, h - 2);
    ctx.lineTo(r, h - 2);
    ctx.quadraticCurveTo(2, h - 2, 2, h - r);
    ctx.lineTo(2, r);
    ctx.quadraticCurveTo(2, 2, r, 2);
    ctx.closePath();
  }

  function platePicture(THREE, station) {
    const ink = station.stage2 ? INK.pending : (station.filled ? INK.lit : INK.dark);
    const canvas = document.createElement("canvas");
    canvas.width = CANVAS_W;
    canvas.height = CANVAS_H;
    const ctx = canvas.getContext("2d");

    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    ctx.fillStyle = ink.face;
    ctx.strokeStyle = ink.edge;
    ctx.lineWidth = station.filled ? 5 : 3;
    /* The three stations stage 1 cannot fill are drawn with a broken edge.
     * A dashed border is the one visual that reads as "not finished" rather
     * than "empty" without a word of explanation. */
    if (station.stage2) ctx.setLineDash([14, 10]);
    roundedBox(ctx, CANVAS_W, CANVAS_H, 22);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = ink.chip;
    ctx.beginPath();
    ctx.arc(44, 46, 22, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = ink.chipInk;
    ctx.font = "bold 24px ui-monospace,Consolas,monospace";
    ctx.textAlign = "center";
    ctx.fillText(String(station.n), 44, 55);

    ctx.textAlign = "left";
    ctx.fillStyle = ink.title;
    ctx.font = "bold 26px system-ui,Segoe UI,sans-serif";
    ctx.fillText(String(station.label).slice(0, 26), 78, 56);

    let y = 100;
    if (station.head) {
      ctx.fillStyle = ink.title;
      ctx.font = "20px system-ui,Segoe UI,sans-serif";
      for (const line of wrap(ctx, station.head, CANVAS_W - 52, 2)) {
        ctx.fillText(line, 26, y);
        y += 26;
      }
      y += 4;
    }

    ctx.fillStyle = ink.body;
    ctx.font = "18px system-ui,Segoe UI,sans-serif";
    const body = station.stage2
      ? ["not answerable from the live route - see the note"]
      : (station.rows || []).filter(Boolean);
    let left = station.stage2 ? 2 : 4;
    for (const row of body) {
      if (left <= 0 || y > CANVAS_H - 46) break;
      for (const line of wrap(ctx, row, CANVAS_W - 52, 1)) {
        ctx.fillText(line, 26, y);
        y += 24;
      }
      left -= 1;
    }

    /* The leaf count, bottom right: how many things actually contributed.
     * It is the number the operator scans the stage for. */
    const leaves = (station.leaves || []).length;
    if (leaves) {
      const on = station.leaves.filter((l) => l && l.on).length;
      ctx.textAlign = "right";
      ctx.fillStyle = ink.chip;
      ctx.font = "bold 19px system-ui,Segoe UI,sans-serif";
      ctx.fillText(on + " of " + leaves + " in the prompt", CANVAS_W - 26,
        CANVAS_H - 22);
      ctx.textAlign = "left";
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.anisotropy = 4;
    return texture;
  }

  /* ------------------------------------------------------------- layout */

  /* Serpentine: 1-5 left to right along the top, 6-10 right to left along
   * the bottom. A single row of ten would be 42 units wide - the shape
   * that forces the RapAssembly camera out to +/-43 and makes the whole
   * thing unreadable on a tablet. Folded, it is 17 wide, which fits a 9"
   * landscape screen with type still legible. */
  function spots(count) {
    const out = [];
    for (let i = 0; i < count; i += 1) {
      const row = Math.floor(i / COLUMNS);
      const column = row % 2 === 0 ? i % COLUMNS : COLUMNS - 1 - (i % COLUMNS);
      out.push([
        (column - (COLUMNS - 1) / 2) * GAP_X,
        -(row - (Math.ceil(count / COLUMNS) - 1) / 2) * GAP_Y
      ]);
    }
    return out;
  }

  /* Solve for the distance that contains the plates in BOTH axes. Placing
   * the camera by hand is what makes every other 3js panel on this station
   * desktop-only. */
  function fitCamera(camera, points, aspect) {
    let halfW = PLATE_W / 2;
    let halfH = PLATE_H / 2;
    for (const [x, y] of points) {
      halfW = Math.max(halfW, Math.abs(x) + PLATE_W / 2);
      halfH = Math.max(halfH, Math.abs(y) + PLATE_H / 2);
    }
    const margin = 1.12;
    const vertical = Math.tan((camera.fov * Math.PI) / 360);
    const byHeight = (halfH * margin) / vertical;
    const byWidth = (halfW * margin) / (vertical * Math.max(0.2, aspect));
    camera.position.set(0, 0, Math.max(byHeight, byWidth));
    camera.updateProjectionMatrix();
  }

  /* --------------------------------------------------------------- open */

  function close() {
    if (!live) return;
    const stage = live;
    live = null;
    try { cancelAnimationFrame(stage.frame); } catch (err) { /* gone */ }
    try { stage.renderer.dispose(); } catch (err) { /* gone */ }
    try { window.removeEventListener("resize", stage.onResize); } catch (err) {}
    try {
      if (stage.renderer.domElement.parentNode) {
        stage.renderer.domElement.parentNode.removeChild(stage.renderer.domElement);
      }
    } catch (err) { /* gone */ }
  }

  /* host is the element the canvas fills; lineage is what read() returned.
   * Nothing is fetched here - the payload has already arrived. */
  async function open(host, lineage, baseUrl) {
    close();
    if (!host) return null;
    const THREE = await preload(baseUrl);
    if (!THREE) throw new Error("three.js did not load");

    const stations = (lineage && lineage.spine) || [];
    const points = spots(stations.length || 10);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x04070b);
    const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 200);
    const renderer = new THREE.WebGLRenderer({antialias: true});
    renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2));
    host.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "width:100%;height:100%;display:block";
    scene.add(new THREE.AmbientLight(0xffffff, 1));

    const plates = stations.map((station, i) => {
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(PLATE_W, PLATE_H),
        new THREE.MeshBasicMaterial({transparent: true}));
      mesh.material.map = platePicture(THREE, station);
      mesh.position.set(points[i][0], points[i][1], 0);
      scene.add(mesh);
      return mesh;
    });

    /* One connector per hand-off, and a light that walks it. The light is
     * dimmed where the hand-off runs into a station stage 1 cannot see,
     * so the two gaps in the line are visible at a glance. */
    const links = [];
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = new THREE.Vector3(points[i][0], points[i][1], 0);
      const b = new THREE.Vector3(points[i + 1][0], points[i + 1][1], 0);
      const known = !(stations[i + 1] || {}).stage2;
      scene.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([a, b]),
        new THREE.LineBasicMaterial({color: known ? 0x22304a : 0x4a3a16})));
      const spark = new THREE.Mesh(
        new THREE.SphereGeometry(0.1, 12, 12),
        new THREE.MeshBasicMaterial({color: known ? 0x4ec9c9 : 0xe3be63}));
      scene.add(spark);
      links.push({a, b, spark, at: i * 0.1});
    }

    const fit = () => {
      const w = host.clientWidth || 900;
      const h = host.clientHeight || 600;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      fitCamera(camera, points, camera.aspect);
    };
    fit();
    window.addEventListener("resize", fit);

    let t = 0;
    const tick = () => {
      if (!live) return;
      /* A hidden tab and a mounted-but-inactive view still fire rAF in
       * Electron with backgroundThrottling off (main.js:701 sets it for the
       * LCD producer). offsetParent is null when the shell or rail has put
       * the Script host behind another view, so neither case spends a frame
       * animating and rendering an invisible WebGL scene. */
      if (!document.hidden && host.offsetParent !== null) {
        t += 0.016;
        for (let i = 0; i < links.length; i += 1) {
          const link = links[i];
          link.at = (link.at + 0.004) % 1;
          link.spark.position.lerpVectors(link.a, link.b, link.at);
        }
        for (let i = 0; i < plates.length; i += 1) {
          plates[i].position.z = Math.sin(t * 0.8 + i) * 0.05;
        }
        renderer.render(scene, camera);
      }
      live.frame = requestAnimationFrame(tick);
    };

    live = {renderer, camera, scene, resize: fit, onResize: fit, frame: 0};
    live.frame = requestAnimationFrame(tick);
    return live;
  }

  const api = {
    preload,
    open,
    close,
    resize: () => { if (live) live.resize(); },
    isOpen: () => !!live,
    /* Exported so the geometry can be reasoned about without a GPU - the
     * layout and the camera fit are the two parts of this file that can
     * be wrong in a way a screenshot would not show. */
    spots,
    fitCamera,
    PLATE_W, PLATE_H, COLUMNS
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PineScriptStage = api;
})(typeof window !== "undefined" ? window : globalThis);
