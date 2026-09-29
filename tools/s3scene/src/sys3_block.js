  /* [s3-scene-nav] THE SCENE YOU CAN WALK AROUND, AND ASK.
     "Allow me to pinch and pull and to navigate around this scene." "I want to
     tap on bubbles and elements in this in order to bring up a sidebar that
     brings up details on that element and allowing me to inspect each element
     in depth and make edits to it." (the operator, 2026-09-29)
     Navigation is our own small orbit rig on pointer events (no OrbitControls
     is vendored): one finger / left-drag ORBITS; two fingers PAN and PINCH
     zoom about their midpoint; right-drag, middle-drag, shift-drag and
     space-drag pan on the desk; the wheel zooms about the pointer; a
     double-tap, the frame button or 0 frames everything. The camera eases
     toward where the hand put it (damping) inside a fixed box and a zoom
     range, so it cannot fly off. touch-action is none on the canvas ONLY, so
     the page never scrolls under a gesture; the canvas carries pine-gestures
     so a corner swipe that starts on it is never a hot corner.
     A TAP (not a drag) picks the element under it - System 3, a road, a
     room, a packet, a paper airplane - rings it and opens the inspector
     docked in the pane. Edits go through the existing System 3 doors only
     (PUT /api/system3/tables/{id}, PUT /api/system3/config/section/{name},
     POST /api/system3/settings for the register's roads); each shows what it
     will change, waits for Confirm, reports the live config hash, and Undo
     writes the previous version's part back (GET /api/system3/config?hash=). */
  async function paintSys3() {
    const host = el('div', 's3-sys3');
    const canvas = el('canvas', {class: 'pine-gestures', tabindex: '0', role: 'application',
      'aria-label': 'System 3 scene. Drag to orbit; two fingers, right-drag or space-drag to pan; pinch or wheel to zoom; double-tap or 0 to frame all; tap an element to inspect it.'});
    host.append(canvas);
    const nowNode = el('div', 's3-sys3-now', 'waiting for the line on air...');
    host.append(nowNode, el('div', 's3-sys3-legend', el('span', {text: 'centre: System 3'}), el('span', {text: 'ring: the roads (lit = directed by System 3)'}),
      el('span', {text: 'right: the writer, the recording room, the ledger, the air'}), el('span', {text: 'paper airplanes: decisions landing; packets: the circuits'}),
      el('span', {class: 's3-sys3-hint', text: 'drag: orbit · two fingers / right-drag / space-drag: pan · pinch / wheel: zoom · double-tap: frame all · tap: inspect'})));
    fill(body, el('div', 's3-card', el('h2', {text: 'Sys3 - System 3 and the systems it directs, live'}), host));
    if (sys3) { sys3.stop(); sys3 = null; }
    let THREE; try { THREE = await threeLoad(); } catch (e) { report(e); return; }
    if (tab !== 'sys3' || !canvas.isConnected) return;
    sys3 = sys3Scene(THREE, canvas, nowNode, host);
  }
  function sys3Scene(THREE, canvas, nowNode, host) {
    const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
    camera.position.set(0, 9, 22); camera.lookAt(0, 0, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const light = new THREE.PointLight(0xffffff, 1.0); light.position.set(6, 12, 10); scene.add(light);
    const colour = css => { const name = String(css).replace(/^var\(|\)$/g, ''); const got = getComputedStyle(root).getPropertyValue(name).trim(); return new THREE.Color(got || '#8ac6ac'); };
    const label = (text, p, dy, opacity) => { const c = document.createElement('canvas'); c.width = 256; c.height = 48; const cx = c.getContext('2d');
      cx.fillStyle = '#dfe6e4'; cx.font = '600 22px sans-serif'; cx.textAlign = 'center'; cx.fillText(text, 128, 32);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, opacity})); sp.scale.set(2.8, 0.52, 1); sp.position.copy(p).add(new THREE.Vector3(0, dy, 0)); scene.add(sp); };
    const roads = (status && status.roads) || []; const n = Math.max(1, roads.length); const R = 8;
    const nodes = new Map(); const pickables = [];
    const pickable = (m, kind, radius, data) => { m.userData = Object.assign(m.userData || {}, {kind}, data || {}); pickables.push({m, kind, radius}); return m; };
    const core = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.6, 1.6), new THREE.MeshStandardMaterial({color: 0x8ac6ac, emissive: 0x1f3a33})); scene.add(core); nodes.set('system3', core);
    pickable(core, 'system3', 1.15, {id: 'system3'});
    const lineMat = (c, o) => new THREE.LineBasicMaterial({color: c, transparent: true, opacity: o});
    const circuits = [];
    roads.forEach((r, i) => { const a = (i / n) * Math.PI * 2; const p = new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R * 0.55);
      const on = r.mode === 'active';
      const m = new THREE.Mesh(new THREE.SphereGeometry(on ? 0.42 : 0.3, 16, 12), new THREE.MeshStandardMaterial({color: on ? 0x54d18b : 0x35414c, emissive: on ? 0x10331f : 0x000000}));
      m.position.copy(p); m.userData = {road: r.id, on}; scene.add(m); nodes.set(r.id, m); pickable(m, 'road', on ? 0.5 : 0.4, {id: r.id});
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), p]), lineMat(on ? 0x54d18b : 0x35414c, on ? 0.45 : 0.15)));
      circuits.push({from: new THREE.Vector3(0, 0, 0), to: p, phase: Math.random(), speed: 0.12 + Math.random() * 0.1, on, a: 'system3', b: r.id});
      label(r.id, p, -0.8, on ? 0.95 : 0.5); });
    const rooms = [['writer', 'the writer', 0xf0a6ca], ['voice', 'recording room', 0x87bfff], ['ledger', 'script ledger', 0xe7bf78], ['air', 'on air', 0x7fe0d6]];
    let prevRoom = null, prevId = 'system3';
    rooms.forEach(([id, text, col], i) => { const p = new THREE.Vector3(R + 4.5, 3.4 - i * 2.2, -2 + i * 0.4);
      const m = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.7, 0.7), new THREE.MeshStandardMaterial({color: col})); m.position.copy(p); scene.add(m); nodes.set(id, m);
      pickable(m, 'room', 0.7, {id, text});
      label(text, p, -0.75, 0.95);
      const from = prevRoom ? prevRoom.position.clone() : new THREE.Vector3(0, 0, 0);
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, p]), lineMat(col, 0.5)));
      circuits.push({from, to: p, phase: Math.random(), speed: 0.2, on: true, a: prevId, b: id}); prevRoom = m; prevId = id; });
    const packets = circuits.map((c, i) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 6), new THREE.MeshBasicMaterial({color: 0xffffff})); m.visible = c.on; scene.add(m);
      pickable(m, 'packet', 0.16, {circuit: i}); return m; });
    const planes = []; const planeGeo = new THREE.ConeGeometry(0.22, 0.7, 4);
    const roadOf = new Map(); let cursor = 0, alive = true, raf = 0, lastText = '', thumbSprite = null;
    const ring = [], aired = [];                  /* what this scene saw land: the rooms' recent items */
    const fly = (target, col, ev, road) => { const m = new THREE.Mesh(planeGeo, new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.95})); m.position.set(0, 0.9, 0); scene.add(m);
      pickable(m, 'plane', 0.4, {event: ev, road});
      planes.push({m, to: target.position.clone().add(new THREE.Vector3(0, 0.6, 0)), t: 0}); if (planes.length > 40) { const old = planes.shift(); scene.remove(old.m); } };
    const thumb = (text, dice) => { if (thumbSprite) { scene.remove(thumbSprite); thumbSprite = null; } if (!text) return;
      const c = document.createElement('canvas'); c.width = 512; c.height = 128; const cx = c.getContext('2d');
      cx.fillStyle = '#0b1215ee'; cx.fillRect(0, 0, 512, 128); cx.strokeStyle = '#8ac6ac'; cx.strokeRect(1, 1, 510, 126);
      cx.fillStyle = '#dfe6e4'; cx.font = '20px sans-serif'; let line = '', y = 34;
      for (const w of text.split(' ')) { if (cx.measureText(line + ' ' + w).width > 480) { cx.fillText(line, 16, y); line = w; y += 26; if (y > 86) break; } else line = line ? line + ' ' + w : w; }
      if (y <= 86) cx.fillText(line, 16, y);
      (dice || []).slice(0, 16).forEach((d, i) => { cx.fillStyle = '#87bfff'; const h = Math.max(3, (Number(d) || 0) / 100 * 28); cx.fillRect(16 + i * 30, 120 - h, 22, h); });
      thumbSprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true})); thumbSprite.scale.set(8, 2, 1); thumbSprite.position.set(0, 4.2, 0); scene.add(thumbSprite); };
    async function poll() {
      if (!alive) return;
      try {
        /* the live edge only: a first read from 0 walked the whole ledger from its oldest event */
        if (!cursor) { const head = await request('/api/system3/events?after=0&limit=1'); cursor = Number(head.head || head.cursor || 0); }
        const feed = await request('/api/system3/events?after=' + cursor + '&limit=60');
        for (const e of (feed.events || [])) {
          let road = e.round || roadOf.get(e.conversation_id);
          if (road === undefined) { try { const c = await request('/api/system3/conversation/' + encodeURIComponent(e.conversation_id)); road = (c.identity || {}).road_kind || ''; } catch (_) { road = ''; } roadOf.set(e.conversation_id, road); }
          ring.push(Object.assign({}, e, {road})); if (ring.length > 200) ring.shift();
          fly(nodes.get(road) || nodes.get('writer'), e.kind === 'observation' ? 0x7fe0d6 : colour(FAM[e.family] || 'var(--obs)').getHex(), e, road);
        }
        cursor = Number(feed.cursor || feed.head || cursor);
        const live = await request('/api/system3/now'); const s3 = live && live.system3; const line = live && live.line;
        const text = line ? `${line.name || line.who || ''}: ${line.text || ''}` : '';
        if (text !== lastText) { lastText = text; thumb(text ? text.slice(0, 220) : '', s3 && s3.turn ? (s3.turn.rolls || []).map(r => r.dice).filter(x => x != null) : []);
          if (text) { aired.push({at: Date.now() / 1000, text, line, road: s3 ? s3.road : ''}); if (aired.length > 30) aired.shift(); }
          nowNode.textContent = text ? (s3 ? `${s3.road} round · turn ${(s3.turn || {}).turn || '?'} of ${s3.turns} · ` : 'not directed by System 3 · ') + text.slice(0, 160) : 'nothing on air'; }
        nodes.forEach((m, id) => { if (m.userData && m.userData.road) m.material.emissive.setHex(s3 && s3.road === id && text ? 0x2a6b3f : (m.userData.on ? 0x10331f : 0x000000)); });
      } catch (e) { /* the scene keeps turning */ }
      if (alive) setTimeout(poll, 2000);
    }

    /* ---- the camera rig: goal (where the hand put it) and cur (eased toward it) ---- */
    const V = (x, y, z) => new THREE.Vector3(x, y, z);
    const LIM = {rMin: 3.5, rMax: 70, phiMin: 0.12, phiMax: 2.3, box: new THREE.Box3(V(-20, -10, -18), V(26, 12, 18))};
    const goal = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2}, cur = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2};
    let home = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2}, drift = true;
    const clampGoal = () => { goal.r = Math.min(LIM.rMax, Math.max(LIM.rMin, goal.r)); goal.phi = Math.min(LIM.phiMax, Math.max(LIM.phiMin, goal.phi)); LIM.box.clampPoint(goal.target, goal.target); };
    const place = st => { const s = Math.sin(st.phi); camera.position.set(st.target.x + st.r * s * Math.sin(st.theta), st.target.y + st.r * Math.cos(st.phi), st.target.z + st.r * s * Math.cos(st.theta)); camera.lookAt(st.target); camera.updateMatrixWorld(); };
    const hand = () => { drift = false; };
    function frameAll(snap) {                     /* double-tap, 0, the frame button: everything in view */
      const box = new THREE.Box3(); const tmp = V(0, 0, 0);
      pickables.forEach(it => { if (it.kind === 'system3' || it.kind === 'road' || it.kind === 'room') box.expandByPoint(it.m.getWorldPosition(tmp)); });
      box.expandByPoint(V(0, 4.8, 0)); box.expandByPoint(V(0, -1.2, 0));
      const sz = box.getSize(V(0, 0, 0)), mid = box.getCenter(V(0, 0, 0));
      const vf = camera.fov * Math.PI / 180; const hf = 2 * Math.atan(Math.tan(vf / 2) * Math.max(0.2, camera.aspect));
      const fit = Math.max((sz.y / 2 + 1.2) / Math.tan(vf / 2), (sz.x / 2 + 1.6) / Math.tan(hf / 2)) + sz.z / 2;
      home = {target: mid, r: Math.min(LIM.rMax, Math.max(8, fit)), theta: 0, phi: 1.2};
      goal.target.copy(home.target); goal.r = home.r; goal.theta = 0; goal.phi = home.phi; clampGoal(); drift = true;
      if (snap) { cur.target.copy(goal.target); cur.r = goal.r; cur.theta = goal.theta; cur.phi = goal.phi; }
    }
    const pos = e => { const r = canvas.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
    const raycaster = new THREE.Raycaster();
    function panPx(dx, dy) {
      const h = canvas.clientHeight || 400; const per = 2 * goal.r * Math.tan(camera.fov * Math.PI / 360) / h;
      const right = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 0), up = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 1);
      goal.target.addScaledVector(right, -dx * per).addScaledVector(up, dy * per); clampGoal(); hand();
    }
    function zoomAt(s, p) {                       /* about the pointer: o1 = p - (p - o0) * s */
      const r1 = Math.min(LIM.rMax, Math.max(LIM.rMin, goal.r * s)); const k = r1 / goal.r;
      if (p && canvas.clientWidth) {
        raycaster.setFromCamera(new THREE.Vector2(p.x / canvas.clientWidth * 2 - 1, -(p.y / canvas.clientHeight) * 2 + 1), camera);
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(V(0, 0, 0)), goal.target);
        const hit = raycaster.ray.intersectPlane(plane, V(0, 0, 0));
        if (hit) goal.target.sub(hit).multiplyScalar(k).add(hit);
      }
      goal.r = r1; clampGoal(); hand();
    }
    /* ---- picking: nearest element on screen, relative to its projected size plus a finger's slop ---- */
    function pickAt(p, touch) {
      const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1; const f = h / 2 / Math.tan(camera.fov * Math.PI / 360);
      const wp = V(0, 0, 0); let best = null;
      for (const it of pickables) {
        if (!it.m.visible || !it.m.parent) continue;
        it.m.getWorldPosition(wp); const dist = camera.position.distanceTo(wp); const q = wp.clone().project(camera);
        if (q.z > 1 || q.z < -1) continue;
        const sx = (q.x + 1) / 2 * w, sy = (1 - q.y) / 2 * h; const pr = it.radius * f / Math.max(0.01, dist);
        const reach = pr + (touch ? 22 : 8); const d = Math.hypot(sx - p.x, sy - p.y);
        if (d > reach) continue;
        const score = d / reach;                  /* a packet tapped dead-on beats the sphere it passes */
        if (!best || score < best.score - 0.02 || (Math.abs(score - best.score) <= 0.02 && dist < best.dist)) best = {it, score, dist};
      }
      return best ? best.it : null;
    }
    const halo = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const cx = c.getContext('2d');
      cx.strokeStyle = '#ffd36b'; cx.lineWidth = 9; cx.beginPath(); cx.arc(64, 64, 52, 0, Math.PI * 2); cx.stroke();
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, depthTest: false})); sp.visible = false; sp.renderOrder = 9; scene.add(sp); return sp; })();
    let sel = null;
    /* ---- the hand ---- */
    const ptrs = new Map(); let mode = '', tapC = null, lastTap = null, multi = false, space = false, over = false, hoverAt = 0;
    const editable = t => !!(t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '')));
    function onDown(e) {
      if (e.pointerType === 'mouse' && e.button > 2) return;
      e.preventDefault(); e.stopPropagation();
      try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* old engine */ }
      try { canvas.focus({preventScroll: true}); } catch (_) { /* old engine */ }
      const p = pos(e); ptrs.set(e.pointerId, p);
      if (ptrs.size === 1) {
        multi = false;
        mode = (e.pointerType === 'mouse' && (e.button === 1 || e.button === 2 || space || e.shiftKey)) ? 'pan' : 'orbit';
        tapC = (e.pointerType !== 'mouse' || e.button === 0) && !space ? {id: e.pointerId, x: p.x, y: p.y, t: performance.now(), touch: e.pointerType !== 'mouse'} : null;
      } else { multi = true; tapC = null; mode = 'pinch'; }
      canvas.classList.toggle('s3-grabbing', mode !== 'orbit' || e.pointerType === 'mouse');
    }
    function onMove(e) {
      const p = pos(e);
      if (!ptrs.has(e.pointerId)) {
        if (e.pointerType === 'mouse' && performance.now() - hoverAt > 60) { hoverAt = performance.now(); canvas.style.cursor = space ? 'grab' : pickAt(p, false) ? 'pointer' : 'grab'; }
        return;
      }
      e.preventDefault(); e.stopPropagation();
      const was = ptrs.get(e.pointerId);
      if (tapC && tapC.id === e.pointerId) {
        if (Math.hypot(p.x - tapC.x, p.y - tapC.y) <= (tapC.touch ? 10 : 5)) return;   /* still a tap: the camera holds */
        tapC = null;
      }
      if (mode === 'pinch' && ptrs.size >= 2) {
        const other = [...ptrs.entries()].find(([id]) => id !== e.pointerId)[1];
        const d0 = Math.hypot(was.x - other.x, was.y - other.y), d1 = Math.hypot(p.x - other.x, p.y - other.y);
        const m0 = {x: (was.x + other.x) / 2, y: (was.y + other.y) / 2}, m1 = {x: (p.x + other.x) / 2, y: (p.y + other.y) / 2};
        if (d0 > 2 && d1 > 2) zoomAt(d0 / d1, m1);
        panPx(m1.x - m0.x, m1.y - m0.y);
      } else if (ptrs.size === 1) {
        const dx = p.x - was.x, dy = p.y - was.y; const h = canvas.clientHeight || 400;
        if (mode === 'pan') panPx(dx, dy);
        else { goal.theta -= 2 * Math.PI * dx / h * 0.7; goal.phi -= 2 * Math.PI * dy / h * 0.7; clampGoal(); hand(); }
      }
      ptrs.set(e.pointerId, p);
    }
    function onUp(e) {
      if (!ptrs.has(e.pointerId)) return;
      e.stopPropagation();
      ptrs.delete(e.pointerId);
      try { canvas.releasePointerCapture(e.pointerId); } catch (_) { /* gone */ }
      if (e.type === 'pointerup' && tapC && tapC.id === e.pointerId && !multi && performance.now() - tapC.t < 700) onTap(pos(e), tapC.touch);
      tapC = null;
      mode = ptrs.size === 1 ? 'orbit' : ptrs.size ? mode : '';
      if (!ptrs.size) canvas.classList.remove('s3-grabbing');
    }
    function onTap(p, touch) {
      const now = performance.now();
      if (lastTap && now - lastTap.t < 360 && Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 30) { lastTap = null; frameAll(); return; }
      lastTap = {t: now, x: p.x, y: p.y};
      const it = pickAt(p, touch);
      if (it) select(it);
    }
    const onWheel = e => { e.preventDefault(); e.stopPropagation(); const d = e.deltaY * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1); zoomAt(Math.exp(Math.max(-300, Math.min(300, d)) * 0.0015), pos(e)); };
    const noMenu = e => e.preventDefault();
    const stopTouch = e => { e.preventDefault(); e.stopPropagation(); };   /* an old WebView still scrolls on touch without this */
    const onKey = e => {
      if (e.key === 'Escape' && !side.hidden) { e.preventDefault(); e.stopPropagation(); closeSide(); return; }
      if (editable(e.target) || !(over || document.activeElement === canvas)) return;
      if (e.key === ' ') { e.preventDefault(); if (!space) { space = true; canvas.style.cursor = 'grab'; } }
      else if (e.key === '0' || e.key === 'f' || e.key === 'F') { e.preventDefault(); frameAll(); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(0.8, null); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAt(1.25, null); }
    };
    const onKeyUp = e => { if (e.key === ' ') space = false; };
    const onBlur = () => { space = false; };
    const onOver = () => { over = true; }, onOut = () => { over = false; };
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('lostpointercapture', onUp);
    canvas.addEventListener('wheel', onWheel, {passive: false});
    canvas.addEventListener('contextmenu', noMenu);
    canvas.addEventListener('touchstart', stopTouch, {passive: false});
    canvas.addEventListener('touchmove', stopTouch, {passive: false});
    canvas.addEventListener('pointerenter', onOver); canvas.addEventListener('pointerleave', onOut);
    window.addEventListener('keydown', onKey, true);          /* window capture: before any document-level Escape */
    window.addEventListener('keyup', onKeyUp, true);
    window.addEventListener('blur', onBlur);
    const frameBtn = el('button', {type: 'button', class: 's3-sys3-frame', title: 'Frame all (double-tap, or 0)', 'aria-label': 'Frame all',
      onclick: () => frameAll()});
    { const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:maximize') : ''; if (svg) frameBtn.innerHTML = svg; else frameBtn.textContent = 'Frame'; }
    host.append(frameBtn);

    /* ---- the inspector, docked in the pane ---- */
    const sideKind = el('span', 's3-pill'), sideTitle = el('h3'), sideNote = el('div', 's3-sys3-snote'), sideBody = el('div', 's3-sys3-sbody');
    const xBtn = el('button', {type: 'button', class: 's3-sys3-x', title: 'Close the inspector (Esc)', 'aria-label': 'Close the inspector', onclick: () => closeSide()});
    { const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:close--filled') : ''; if (svg) xBtn.innerHTML = svg; else xBtn.textContent = '×'; }
    const side = el('aside', {class: 's3-sys3-side', role: 'complementary', 'aria-label': 'Inspector'},
      el('header', 's3-sys3-shead', sideKind, sideTitle, xBtn), sideNote, sideBody);
    side.hidden = true;
    host.append(side);
    const offBack = window.PineDismiss && typeof window.PineDismiss.onBack === 'function'
      ? window.PineDismiss.onBack(() => (side.hidden || !side.isConnected ? null : {node: side, close: closeSide})) : null;
    let insp = 0;
    /* the inspector spans only the part of the scene on the glass: in a short pane the scene's
       foot can sit below the fold, and a sidebar reaching down there would hide its own buttons */
    const fitSide = () => { if (side.hidden) return; const r = host.getBoundingClientRect(); const vh = window.innerHeight || r.bottom;
      side.style.top = Math.max(0, Math.round(-r.top)) + 'px'; side.style.bottom = Math.max(0, Math.round(r.bottom - vh)) + 'px'; };
    window.addEventListener('scroll', fitSide, true); window.addEventListener('resize', fitSide);
    function closeSide() {
      side.hidden = true; host.classList.remove('s3-side-open'); sel = null; halo.visible = false; insp += 1;
      try { canvas.focus({preventScroll: true}); } catch (_) { /* gone */ }
    }
    function select(it, keepNote) {
      sel = it; halo.visible = true;
      side.hidden = false; host.classList.add('s3-side-open'); fitSide(); if (!keepNote) fill(sideNote);
      const d = it.m.userData || {};
      const token = ++insp;
      const put2 = (kind, title, ...kids) => { if (token !== insp) return; sideKind.textContent = kind; sideTitle.textContent = title; fill(sideBody, ...kids); };
      const later = (node, fn) => { Promise.resolve().then(fn).then(kids => { if (token === insp && node.isConnected) fill(node, ...[].concat(kids || [])); },
        e => { if (token === insp && node.isConnected) fill(node, para('Could not read: ' + (e && e.message || e), 's3-error')); }); return node; };
      if (it.kind === 'road') put2('road', d.id, ...roadView(d.id, later));
      else if (it.kind === 'system3') put2('System 3', 'the conversation director', ...coreView(later));
      else if (it.kind === 'room') put2('room', d.text || d.id, ...roomView(d.id, later));
      else if (it.kind === 'packet') put2('packet', 'a circuit', ...packetView(circuits[d.circuit] || {}, later));
      else if (it.kind === 'plane') put2('paper airplane', 'a decision landing', ...planeView(d.event || {}, d.road || '', later));
    }
    /* the inspector's parts */
    const sec = (title, ...kids) => el('section', 's3-sys3-sec', el('h4', {text: title}), ...kids);
    const kv = pairs => el('table', 's3-sys3-kv', el('tbody', null, ...pairs.filter(p => p && p[1] != null && p[1] !== '').map(([k, v]) =>
      el('tr', null, el('th', {text: k}), el('td', null, v && v.nodeType ? v : String(v))))));
    const wait = () => el('p', {class: 's3-muted', text: 'reading...'});
    const fold = (title, value) => el('details', 's3-sys3-fold', el('summary', {text: title}), el('pre', {text: json(value)}));
    const goTab = (id, prep) => { try { if (prep) prep(); } catch (_) { /* the tab opens anyway */ } stopExtras(); tab = id; paint(); };
    const link = (text, fn, title) => btn(text, fn, {class: 's3-sys3-link', title: title || text});
    const cfgNow = () => (config && config.config) || {};
    const liveHash = () => (config && config.hash) || (status && status.config_hash) || '';
    const PREFIX = {caller: ['call'], ad: ['ad', 'ads'], ad_spot: ['ad', 'ads'], manager: ['manager', 'upstairs'], upstairs: ['upstairs', 'manager'],
      banter: ['banter', 'host', 'seat', 'heat'], h3_speak: ['h3'], station_id: ['station', 'dj.station_ids'], interject: ['dj.interject_phrases'],
      request: ['dj.request_phrases'], open: ['dj.open_phrases'], open_show: ['dj.intro_phrases'], sfxguy: ['sfxguy'], track_talk: ['records']};
    const prefixes = id => [id].concat(PREFIX[id] || []);
    const underPrefix = (cid, id) => prefixes(id).some(p => cid === p || cid.startsWith(p + '.'));
    let listsCache = null;
    const listsOf = () => (listsCache ||= request('/api/system3/lists').then(g => (g && g.lists) || [], () => []));
    let segCache = null;
    const segmentsOf = () => { if (!segCache || Date.now() - segCache.at > 30000) segCache = {at: Date.now(), p: request('/api/system3/segments?limit=40')}; return segCache.p; };

    /* EDITS: what will change -> Confirm -> saved (hash) -> Undo (the previous version's part) */
    function flatDiff(a, b, path, out) {
      if (out.length > 60) return out;
      if (a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b)) {
        const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
        keys.forEach(k => flatDiff(a[k], b[k], path ? path + '.' + k : k, out));
      } else if (JSON.stringify(a) !== JSON.stringify(b)) out.push([path || '(all)', a, b]);
      return out;
    }
    const show = v => v === undefined ? '(none)' : typeof v === 'object' ? JSON.stringify(v).slice(0, 80) : String(v);
    function propose({title, changes, apply, undo, after}) {
      if (!changes.length) { fill(sideNote, el('div', 's3-sys3-edit', para('Nothing changed - nothing to save.', 's3-muted'))); return; }
      const card = el('div', {class: 's3-sys3-edit', role: 'alertdialog', 'aria-label': 'Confirm the edit'},
        el('b', {text: title}), el('p', {class: 's3-muted', text: 'This will change:'}),
        el('ul', null, ...changes.slice(0, 40).map(([k, a, b]) => el('li', null, el('code', {text: k}), ' ', show(a), ' -> ', el('b', {text: show(b)})))),
        changes.length > 40 ? para('... and ' + (changes.length - 40) + ' more', 's3-muted') : null);
      const was = liveHash();
      const confirmB = btn('Confirm', async () => {
        confirmB.disabled = true; cancelB.disabled = true;
        try {
          const res = await apply();
          const h = (res && res.hash) || '';
          try { await loadConfig(); await refreshStatus(); } catch (_) { /* the save stands */ }
          saved(title, res);
          const undoB = btn('Undo', async () => {
            undoB.disabled = true;
            try {
              const back = await undo(was);
              try { await loadConfig(); await refreshStatus(); } catch (_) { /* the undo stands */ }
              fill(card, el('b', {text: 'Undone: ' + title}), para('Put back as it was' + (back && back.hash ? ' - live config ' + back.hash : '') + (was ? ' (the version before was ' + was + ').' : '.'), 's3-ok'));
              if (after) after();
            } catch (e) { undoB.disabled = false; card.append(para('Undo failed: ' + e.message, 's3-error')); }
          }, {class: 's3-sys3-undo', title: 'Write the previous version back'});
          fill(card, el('b', {text: 'Saved: ' + title}),
            para(h ? 'Live config ' + h + (was ? ' (was ' + was + ')' : '') + '. The desk uses it from the next round.' : 'Saved (settings are not part of the config; config stays ' + (liveHash() || '?') + ').', 's3-ok'),
            el('div', 's3-row', undoB));
          if (after) after();
        } catch (e) { confirmB.disabled = false; cancelB.disabled = false; card.append(para('Not saved: ' + e.message, 's3-error')); }
      }, {class: 's3-sys3-confirm'});
      const cancelB = btn('Cancel', () => fill(sideNote), {class: 's3-sys3-cancel'});
      card.append(el('div', 's3-row', confirmB, cancelB));
      fill(sideNote, card);
      try { side.scrollTop = 0; } catch (_) { /* fine */ }
    }
    const prevPart = async (was, pick) => { if (!was) throw new Error('no previous version is known'); const got = await request('/api/system3/config?hash=' + encodeURIComponent(was)); return pick(got.config || {}); };
    function tableEditor(t, onlyCats) {                 /* weight, on/off, category weights (and a pool's options) */
      const d = JSON.parse(JSON.stringify(t));
      const cats = (d.categories || []).filter(c => !onlyCats || onlyCats(c.id));
      const numIn = (obj, key, step) => el('input', {type: 'number', min: 0, step: step || 0.1, value: obj[key] == null ? '' : obj[key], class: 's3-sys3-num',
        'aria-label': key, oninput: e => { obj[key] = e.target.value === '' ? obj[key] : +e.target.value; }});
      const catRow = c => {
        const items = (c.items || []).slice(0, 30).map(it => el('li', null, el('label', 's3-row',
          el('input', {type: 'checkbox', checked: it.enabled !== false, 'aria-label': 'on: ' + (it.label || it.id), onchange: e => { it.enabled = e.target.checked; }}),
          el('span', {text: it.label || it.id}), 'odds' in it ? numIn(it, 'odds', 0.05) : ('weight' in it ? numIn(it, 'weight') : null))));
        return el('li', {class: 's3-sys3-cat', 'data-cat': c.id}, el('div', 's3-row', el('span', {text: c.label || c.id}),
          'odds' in c ? numIn(c, 'odds', 0.05) : numIn(c, 'weight')),
          items.length ? el('details', null, el('summary', {text: (c.items || []).length + ' options'}), el('ul', null, ...items)) : null);
      };
      const review = btn('Review the change', () => propose({
        title: 'table ' + t.id, changes: flatDiff(t, d, '', []),
        apply: () => send('/api/system3/tables/' + encodeURIComponent(t.id), 'PUT', d),
        undo: async was => { const old = await prevPart(was, c => (c.tables || []).find(x => x.id === t.id)); if (!old) throw new Error('table ' + t.id + ' was not in ' + was); return send('/api/system3/tables/' + encodeURIComponent(t.id), 'PUT', old); },
        after: () => { if (sel) select(sel, true); }}), {class: 's3-sys3-review', title: 'See what will change before it is saved'});
      return el('details', {class: 's3-sys3-table', 'data-table': t.id},
        el('summary', null, el('b', {text: t.id}), ' ', el('span', {class: 's3-muted', text: (t.family || '') + ' · v' + (t.version || 1) + (t.enabled === false ? ' · off' : '')})),
        el('p', {class: 's3-muted', text: t.label || t.description || ''}),
        el('div', 's3-row', el('label', 's3-row', el('input', {type: 'checkbox', checked: d.enabled !== false, 'aria-label': 'table on', onchange: e => { d.enabled = e.target.checked; }}), 'on'),
          el('span', {text: 'weight'}), numIn(d, 'weight')),
        cats.length ? el('ul', 's3-sys3-cats', ...cats.map(catRow)) : para('No categories here.', 's3-muted'),
        el('div', 's3-row', review, link('Open in Tables', () => goTab('tables', () => { listId = ''; tableId = t.id; draft = null; }), 'Open this table in the Tables tab')));
    }

    function roadView(id, later) {
      const r = ((status && status.roads) || []).find(x => x.id === id) || {id};
      const c = cfgNow(); const st = id === 'banter' ? c.structure : (c.structures || {})[id];
      const legList = st ? (st.legs || st.steps || []) : [];
      const fams = new Set(), named = new Set();
      legList.forEach(l => (l.draws || []).forEach(dr => { if (dr.family) fams.add(dr.family); (dr.tables || []).forEach(x => named.add(x)); }));
      const tbls = (c.tables || []).filter(t => named.has(t.id) || fams.has(t.family) || (t.roads || []).includes(id));
      const pools = (c.tables || []).filter(t => (t.family === 'POOL' || t.family === 'CHANCE') && (t.categories || []).some(k => underPrefix(k.id, id)));
      const sset = settings && settings.settings; const canToggle = !!(sset && (settings.roads || []).includes(id));
      const inList = !!(sset && (sset.roads || []).includes(id));
      const toggle = canToggle ? btn(inList ? 'Stand this road aside' : 'Direct this road', () => {
        const before = (sset.roads || []).slice(); const next = inList ? before.filter(x => x !== id) : before.concat([id]);
        propose({title: 'register: ' + id + (inList ? ' stands aside' : ' directed'), changes: [['settings.roads', before, next]],
          apply: async () => { const res = await send('/api/system3/settings', 'POST', {roads: next}); settings.settings = res.settings; return res; },
          undo: async () => { const res = await send('/api/system3/settings', 'POST', {roads: before}); settings.settings = res.settings; return res; },
          after: () => { if (sel) select(sel, true); }});
      }, {class: 's3-sys3-toggle', title: 'The selected-roads list the "active on selected roads" mode directs'}) : null;
      return [
        sec('Register',
          kv([['label', r.label], ['id', r.id], ['shape', r.shape], ['mode', el('span', {class: 's3-pill ' + (r.mode === 'active' ? 'active' : r.mode === 'shadow' ? 'shadow' : 'off'), text: r.mode || '?'})],
            ['directed', r.mode === 'active' ? 'yes - directed by System 3' : (r.label_air || 'no')], ['what', r.what], ['writer', r.writer], ['hook', r.hook], ['structure', r.structure],
            ['selected list', sset ? (inList ? 'in it' : 'not in it') + (sset.mode !== 'active_selected_roads' ? ' (mode is ' + sset.mode + '; the list decides only in active on selected roads)' : '') : '']]),
          el('div', 's3-row', toggle, link('Segments editor', () => goTab('segments', () => { if (!segNodes || segRoadOf !== id) { segNodes = null; segLoad(id); } segRoad = id; segSel = {node: -1, draw: -1}; }), 'Open this road in the Segments node editor'),
            link('Structure', () => goTab('structure', () => { if (structRoad !== id) { structRoad = id; steps = null; legs = null; } }), 'Open this road on the Structure tab'))),
        sec('Legs' + (st ? ' - ' + (st.label || st.id || '') + ' v' + (st.version || 1) : ''),
          legList.length ? el('ol', 's3-sys3-legs', ...legList.map(l => el('li', null, el('b', {text: l.label || l.id}), ' ',
            el('span', {class: 's3-muted', text: [l.seat || l.speaker, l.place, l.optional ? 'optional' : ''].filter(Boolean).join(' · ')}),
            el('div', {class: 's3-sys3-draws', text: (l.draws || []).map(dr => dr.family + (dr.tables ? '[' + dr.tables.join(',') + ']' : '') + (dr.fixed ? '=' + dr.fixed : '') + (dr.closes ? ' closes' : '')).join('  ') || 'no draws'}))))
            : para(r.shape === 'line' || r.shape === 'node' ? 'A single-voice road: one node, no legs.' : 'No structure saved for this road.', 's3-muted')),
        sec('Tables', tbls.length ? el('div', null, ...tbls.map(t => tableEditor(t))) : para('No table is drawn by this road.', 's3-muted')),
        sec('Pools', pools.length ? el('div', null, ...pools.map(t => tableEditor(t, cid => underPrefix(cid, id)))) : para('No pool rows are named for this road.', 's3-muted'),
          later(el('div'), async () => { const ls = (await listsOf()).filter(l => underPrefix(l.id, id));
            return ls.length ? el('ul', 's3-sys3-lists', ...ls.map(l => el('li', null, el('b', {text: l.label}), ' ', el('span', {class: 's3-muted', text: l.family + ' · ' + (l.count || 0) + ' rows'}), ' ',
              link('Open', () => goTab('tables', () => { listId = l.id; listView.q = ''; listView.state = ''; listView.offset = 0; }), 'Open this list in the Tables tab')))) : null; })),
        sec('Recent lines and their rolls', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=3&road=' + encodeURIComponent(id));
          const convs = (got.conversations || []).slice(0, 2); if (!convs.length) return para('No round recorded on this road in the ledger.', 's3-muted');
          const out = [];
          for (const cv of convs) {
            const full = await request('/api/system3/conversation/' + encodeURIComponent(cv.conversation_id));
            const lines = (full.lines || []).slice(-3);
            out.push(el('div', 's3-sys3-conv', el('div', {class: 's3-muted', text: day(cv.created) + ' · ' + cv.mode + ' · ' + cv.turns + ' turns · ' + (cv.status || '')}),
              lines.length ? el('ul', null, ...lines.map(ln => el('li', null, el('b', {text: (ln.who || '') + ': '}), String(ln.text || '').slice(0, 180),
                later(el('div', 's3-sys3-rolls'), async () => { const o = await request('/api/system3/origin/' + encodeURIComponent(ln.line_id));
                  const rolls = (o.nodes || []).filter(x => x.node === 'roll').slice(0, 8);
                  return rolls.length ? rolls.map(x => el('span', {class: 's3-sys3-roll', title: x.picked || '', text: (x.table || '') + ' ' + (x.dice == null ? '' : 'd' + x.dice) + ' ' + String(x.picked || x.path || '').slice(0, 40)}))
                    : el('span', {class: 's3-muted', text: o.verdict ? o.verdict + (o.why ? ' - ' + o.why : '') : 'no rolls recorded'}); }))))
                : para('planned; no line written to air yet', 's3-muted')));
          }
          return out;
        })),
        sec('Rates and failures', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=40&road=' + encodeURIComponent(id)); const cs = got.conversations || [];
          if (!cs.length) return para('Nothing in the ledger for this road.', 's3-muted');
          const count = f => cs.reduce((m, x) => { const k = f(x) || 'none'; m[k] = (m[k] || 0) + 1; return m; }, {});
          const span = (cs[0].created - cs[cs.length - 1].created) / 3600;
          const fmt = o => Object.entries(o).map(([k, v]) => k + ' ' + v).join(' · ');
          return kv([['rounds read', cs.length], ['rate', span > 0 ? num(cs.length / span, 1) + ' per hour' : '-'], ['status', fmt(count(x => x.status))],
            ['verdicts', fmt(count(x => x.verdict))], ['failed', cs.filter(x => /fail|abandon/.test(String(x.status || '')) || x.verdict === 'non_compliant').length],
            ['station faults (all roads)', (status && status.metrics && status.metrics.failures) || 0], ['last fault', status && status.metrics && status.metrics.last_failure]]);
        })),
        sec('Hour segments', later(wait(), async () => {
          const got = await segmentsOf(); const rows = (got.segments || []).filter(sg => (sg.conversations || []).some(cv => cv.road === id));
          const now = got.now ? el('p', {class: 's3-muted', text: 'on now: ' + (got.now.label || got.now.id)}) : null;
          return [now, rows.length ? el('ul', 's3-sys3-segs', ...rows.slice(0, 12).map(sg => el('li', null, el('b', {text: sg.label || sg.template}), ' ',
            el('span', {class: 's3-muted', text: day(sg.start) + ' · ' + (sg.conversations || []).filter(cv => cv.road === id).length + ' of ' + (sg.conversations || []).length + ' conversations'}))))
            : para('This road went out in none of the last three hours\' segments.', 's3-muted')];
        })),
        fold('register entry (raw)', r)];
    }
    function coreView(later) {
      const m = (status && status.metrics) || {}, stc = (status && status.store) || {}, s = (status && status.settings) || {};
      const c = cfgNow(); const SECTIONS = ['speakerbox', 'sfx', 'sfxguy', 'split', 'personalities', 'blocks'];
      let secName = 'speakerbox';
      const area = el('textarea', {class: 's3-sys3-json', rows: 10, 'aria-label': 'section JSON', value: json(c[secName] || {})});
      const pick = el('select', {'aria-label': 'config section', onchange: e => { secName = e.target.value; area.value = json(cfgNow()[secName] || {}); }},
        ...SECTIONS.map(x => el('option', {value: x, text: x})));
      const review = btn('Review the change', () => {
        let next; try { next = JSON.parse(area.value); } catch (e) { fill(sideNote, el('div', 's3-sys3-edit', para('Not JSON: ' + e.message, 's3-error'))); return; }
        const name = secName; const before = cfgNow()[name] || {};
        propose({title: 'section ' + name, changes: flatDiff(before, next, name, []),
          apply: () => send('/api/system3/config/section/' + name, 'PUT', next),
          undo: async was => send('/api/system3/config/section/' + name, 'PUT', await prevPart(was, cc => cc[name] || before)),
          after: () => { area.value = json(cfgNow()[name] || {}); }});
      }, {class: 's3-sys3-review', title: 'See what will change before it is saved'});
      const active = (c.tables || []).filter(t => t.enabled !== false);
      return [
        sec('Now', kv([['mode', (s.mode || '').replaceAll('_', ' ')], ['selected roads', (s.roads || []).join(', ')], ['engine', status && status.engine], ['config', liveHash()],
          ['planned', m.planned], ['active', m.active], ['shadow', m.shadow], ['plan', num(m.plan_ms_ema, 1) + ' ms'], ['max plan', num(m.plan_ms_max, 1) + ' ms'],
          ['open rounds', status && status.open_rounds], ['lines linked', m.lines_linked], ['failures', m.failures], ['last fault', m.last_failure],
          ['ledger', (stc.conversations || 0) + ' conversations · ' + (stc.events || 0) + ' events · ' + (stc.lines || 0) + ' lines']]),
          el('div', 's3-row', link('Controls', () => goTab('controls'), 'Mode, roads and behaviour controls'), link('Director', () => goTab('director'), 'The conversations, the Rolodex and the script'))),
        sec('Active tables (' + active.length + ')', el('div', null, ...active.map(t => tableEditor(t)))),
        sec('Config sections', el('div', 's3-row', pick, review), area),
        sec('Versions', el('ul', 's3-sys3-vers', ...((config && config.versions) || []).slice(0, 8).map(v => el('li', null, el('code', {text: v.hash}), ' ',
          el('span', {class: 's3-muted', text: day(v.created) + ' · ' + (v.note || '')}), v.hash === liveHash() ? el('span', {class: 's3-pill active', text: 'live'}) : null)))),
        fold('status (raw)', status || {})];
    }
    function roomView(id, later) {
      const m = (status && status.metrics) || {}, stc = (status && status.store) || {};
      const evRow = e => el('li', null, el('span', {class: 's3-muted', text: day(e.at) + ' '}), el('b', {text: (e.family || e.kind || '') + ' '}),
        String(e.label || e.stage || e.key || '').slice(0, 80), e.dice != null ? ' d' + e.dice : '', e.road ? el('span', {class: 's3-muted', text: ' · ' + e.road}) : '');
      const recent = (f, empty) => { const rows = ring.filter(f).slice(-12).reverse(); return rows.length ? el('ul', 's3-sys3-recent', ...rows.map(evRow)) : para(empty, 's3-muted'); };
      if (id === 'writer') return [
        sec('Queue', kv([['open rounds', status && status.open_rounds], ['rounds planned', m.planned], ['lines planned', m.lines_planned], ['lines bound', m.lines_bound],
          ['material resolved', m.material_resolved], ['material timeouts', m.material_timeouts], ['turn-by-turn beats', m.mode_b_beats], ['repairs', m.repairs], ['fallbacks', m.fallbacks]])),
        sec('Recent rounds handed to the writer', later(wait(), async () => { const g = await request('/api/system3/conversations?limit=10'); const cs = g.conversations || [];
          return cs.length ? el('ul', 's3-sys3-recent', ...cs.map(cv => el('li', null, el('span', {class: 's3-muted', text: day(cv.created) + ' '}), el('b', {text: cv.road + ' '}),
            (cv.status || '') + ' · ' + cv.turns + ' turns · ', el('span', {class: 's3-muted', text: String(cv.topic || '').slice(0, 70)})))) : para('Nothing recorded.', 's3-muted'); })),
        link('Director', () => goTab('director'), 'The conversations, the Rolodex and the script')];
      if (id === 'voice') return [
        sec('Queue', kv([['voice from ES', m.perf_applied], ['SFX directed', m.sfx_directed], ['SFX extra', m.sfx_extra], ['SFX observed', m.sfx_observed],
          ['SFX Guy directed', m.sfxguy_directed], ['SFX Guy spoke', m.sfxguy_spoke]])),
        sec('Recent voice rolls this scene saw', recent(e => /^voice\.|^sfx/.test(String(e.key || '')) || e.family === 'SFX', 'None since the scene opened.')),
        link('Controls', () => goTab('controls'), 'The sfx, sfxguy and split sections')];
      if (id === 'ledger') return [
        sec('Queue', kv([['writes pending', m.pending_writes], ['dropped', m.writes_dropped], ['conversations', stc.conversations], ['events', stc.events], ['lines', stc.lines],
          ['segments', stc.segments], ['size', ((stc.bytes || 0) / 1e6).toFixed(1) + ' MB'],
          ['modes', Object.entries(stc.modes || {}).map(([k, v]) => k + ' ' + v).join(' · ')], ['verdicts 24 h', Object.entries(stc.verdicts_24h || {}).map(([k, v]) => k + ' ' + v).join(' · ')]])),
        sec('Recent script-ledger commits', recent(e => e.family === 'COMMIT' || e.stage === 'script-ledger', 'None since the scene opened.')),
        link('Audit', () => goTab('audit'), 'Every recorded decision and observation')];
      return [
        sec('On air now', el('p', {text: lastText || 'nothing on air'})),
        sec('Recent lines on air this scene saw', aired.length ? el('ul', 's3-sys3-recent', ...aired.slice(-12).reverse().map(a => el('li', null,
          el('span', {class: 's3-muted', text: day(a.at) + ' '}), a.road ? el('b', {text: a.road + ' '}) : '', a.text.slice(0, 160),
          a.line && (a.line.id || a.line.line_id) ? later(el('div', 's3-sys3-rolls'), () => originView(a.line.id || a.line.line_id)) : null))) : para('None since the scene opened.', 's3-muted'))];
    }
    async function originView(lineId) {
      const o = await request('/api/system3/origin/' + encodeURIComponent(lineId));
      const rolls = (o.nodes || []).filter(x => x.node === 'roll');
      return [kv([['verdict', o.verdict], ['why', o.why], ['road', o.road], ['text', String(o.text || '').slice(0, 200)]]),
        rolls.length ? el('div', null, ...rolls.slice(0, 12).map(x => el('span', {class: 's3-sys3-roll', title: x.picked || '', text: (x.table || '') + ' ' + (x.dice == null ? '' : 'd' + x.dice) + ' ' + String(x.picked || x.path || '').slice(0, 48)}))) : null,
        fold('origin record (raw)', o)];
    }
    async function replayView(cid) {
      const r = await send('/api/system3/replay/' + encodeURIComponent(cid), 'POST');
      return kv([['replay', r.ok ? 'every draw reproduced' : 'differs'], ['events', r.events], ['replayed', r.replayed], ['first difference', r.first_difference ? JSON.stringify(r.first_difference).slice(0, 120) : ''], ['why', r.why]]);
    }
    const replayBtn = (cid, box) => btn('Replay the rolls', e => { e.target.disabled = true; fill(box, wait()); replayView(cid).then(k => fill(box, k), err => fill(box, para('Replay: ' + err.message, 's3-error'))); },
      {class: 's3-sys3-replay', title: 'Re-draw every decision of this round from its inputs, seed and config'});
    function packetView(cc, later) {
      const road = cc.a === 'system3' && cc.b && !rooms.some(x => x[0] === cc.b) ? cc.b : '';
      const names = {system3: 'System 3', writer: 'the writer', voice: 'the recording room', ledger: 'the script ledger', air: 'the air'};
      const what = road ? 'System 3 hands this road its plan (the rolls of each leg) and the road hands its words back to be bound.'
        : ({writer: 'System 3 hands the writer the running order: each turn\'s decisions as the prompt\'s blocks.',
          voice: 'The writer\'s words go to the recording room with the performance the ES row set.',
          ledger: 'Rendered lines take their place in the script ledger (block, ord).', air: 'The ledger plays out: a line goes to air and the air receipt comes back.'})[cc.b] || '';
      const rb = el('div');
      return [sec('Circuit', kv([['from', names[cc.a] || cc.a], ['to', names[cc.b] || cc.b], ['carries', what], ['live', cc.on ? 'yes' : 'no (road not directed)']])),
        road ? el('div', 's3-row', link('Inspect the road', () => { const it = pickables.find(p => p.kind === 'road' && p.m.userData.id === road); if (it) select(it); }, 'Open this road in the inspector')) : null,
        sec('Its latest decision and origin', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=1' + (road ? '&road=' + encodeURIComponent(road) : '')); const cv = (got.conversations || [])[0];
          if (!cv) return para('Nothing recorded on this circuit.', 's3-muted');
          const full = await request('/api/system3/conversation/' + encodeURIComponent(cv.conversation_id));
          const ln = (full.lines || [])[(full.lines || []).length - 1]; const ev = (full.decision_events || [])[(full.decision_events || []).length - 1];
          return [kv([['round', cv.road + ' · ' + cv.conversation_id], ['when', day(cv.created)], ['status', cv.status], ['decisions', cv.events]]),
            ev ? fold('latest decision ' + (ev.family || '') + ' (raw)', ev) : null,
            ln ? later(el('div'), () => originView(ln.line_id)) : para('No line of it reached the ledger yet.', 's3-muted'),
            el('div', 's3-row', replayBtn(cv.conversation_id, rb)), rb];
        }))];
    }
    function planeView(ev, road, later) {
      const rb = el('div'); const real = ev.conversation_id && !String(ev.conversation_id).startsWith('station:');
      const lineIds = ev.lines || [];
      return [sec('Decision', kv([['kind', ev.kind], ['family', ev.family], ['what', ev.label || ev.stage || ev.key], ['key', ev.key], ['dice', ev.dice], ['odds', ev.odds],
          ['hit', ev.hit == null ? '' : ev.hit ? 'yes' : 'no'], ['why', ev.why], ['road', road || ev.round], ['conversation', ev.conversation_id], ['when', day(ev.at)], ['cursor', ev.cursor]])),
        sec('Origin record', lineIds.length ? later(wait(), () => originView(lineIds[0]))
          : real ? later(wait(), async () => { const full = await request('/api/system3/conversation/' + encodeURIComponent(ev.conversation_id));
            const ln = (full.lines || [])[0]; return ln ? originView(ln.line_id) : para('Its round has no line in the ledger yet.', 's3-muted'); })
            : para('A station roll: it belongs to the station\'s hour, not to one line.', 's3-muted')),
        real ? el('div', 's3-row', replayBtn(ev.conversation_id, rb), link('Audit', () => goTab('audit', () => { auditFilter = {family: '', conversation: ev.conversation_id}; }), 'This round in the Audit log')) : null, rb,
        fold('event (raw)', ev)];
    }

    let framed = false;
    const size = () => { const w = canvas.clientWidth || 640, h = canvas.clientHeight || 400; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
      if (framed && drift && !ptrs.size) frameAll(false); };   /* untouched: the pane's new shape is framed again */
    size(); window.addEventListener('resize', size);
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => size()) : null; if (ro) ro.observe(canvas);
    frameAll(true); framed = true;
    const t0 = performance.now(); const origin = new THREE.Vector3(0, 0.9, 0); let tPrev = t0, frozen = false;
    const hp = V(0, 0, 0);
    function frame() {
      if (!alive) return; raf = requestAnimationFrame(frame);
      const now = performance.now(); const t = (now - t0) / 1000; const dt = Math.min(0.1, (now - tPrev) / 1000); tPrev = now;
      core.rotation.y = t * 0.6; core.rotation.x = Math.sin(t * 0.5) * 0.4;
      circuits.forEach((c, i) => { if (!c.on) return; const u = (t * c.speed + c.phase) % 1; packets[i].position.lerpVectors(c.from, c.to, u); packets[i].position.y += Math.sin(u * Math.PI) * 0.5; });
      for (let i = planes.length - 1; i >= 0; i -= 1) { const p = planes[i]; if (!frozen) p.t += 0.016; const u = Math.min(1, p.t / 1.6);
        p.m.position.lerpVectors(origin, p.to, u); p.m.position.y += Math.sin(u * Math.PI) * 2.2; p.m.lookAt(p.to); p.m.rotateX(Math.PI / 2);
        if (u >= 1) { p.m.material.opacity -= 0.05; if (p.m.material.opacity <= 0) { scene.remove(p.m); planes.splice(i, 1); } } }
      for (let i = pickables.length - 1; i >= 0; i -= 1) if (pickables[i].kind === 'plane' && !pickables[i].m.parent && pickables[i] !== sel) pickables.splice(i, 1);
      if (drift) goal.theta = home.theta + Math.sin(t * 0.1) * 0.13;   /* the old idle sway, until a hand moves the camera */
      const k = 1 - Math.exp(-dt * 9);
      cur.target.lerp(goal.target, k); cur.r += (goal.r - cur.r) * k; cur.theta += (goal.theta - cur.theta) * k; cur.phi += (goal.phi - cur.phi) * k;
      place(cur);
      if (sel && halo.visible) { const ok = sel.m.visible && !!sel.m.parent; halo.material.opacity = ok ? 1 : 0; if (ok) { sel.m.getWorldPosition(hp); halo.position.copy(hp); halo.scale.setScalar(sel.radius * 3.2); } }
      renderer.render(scene, camera);
    }
    frame(); poll();
    /* the harness's handle: the camera goal and picking, read without the GPU */
    const api = {
      stop() {
        alive = false; cancelAnimationFrame(raf); window.removeEventListener('resize', size); if (ro) ro.disconnect();
        window.removeEventListener('keydown', onKey, true); window.removeEventListener('keyup', onKeyUp, true); window.removeEventListener('blur', onBlur);
        window.removeEventListener('scroll', fitSide, true); window.removeEventListener('resize', fitSide);
        if (offBack) { try { offBack(); } catch (_) { /* gone */ } }
        try { renderer.dispose(); } catch (_) { /* gone */ }
      },
      view: () => ({r: goal.r, theta: goal.theta, phi: goal.phi, target: goal.target.toArray(), drift, home: {r: home.r, target: home.target.toArray()}, open: !side.hidden, sel: sel ? sel.kind + ':' + (sel.m.userData.id ?? sel.m.userData.circuit ?? '') : ''}),
      screenOf: (kind, id) => { const it = pickables.find(p => p.kind === kind && (id == null || p.m.userData.id === id || p.m.userData.circuit === id)); if (!it) return null;
        const q = it.m.getWorldPosition(V(0, 0, 0)).project(camera); const r = canvas.getBoundingClientRect();
        return {x: r.left + (q.x + 1) / 2 * r.width, y: r.top + (1 - q.y) / 2 * r.height}; },
      screens: kind => pickables.filter(p => p.kind === kind && p.m.visible && p.m.parent).map(p => { const q = p.m.getWorldPosition(V(0, 0, 0)).project(camera); const r = canvas.getBoundingClientRect();
        return {id: p.m.userData.id ?? p.m.userData.circuit, x: r.left + (q.x + 1) / 2 * r.width, y: r.top + (1 - q.y) / 2 * r.height}; }),
      fly: ev => fly(nodes.get(ev.round || '') || nodes.get('writer'), 0x7fe0d6, ev, ev.round || ''),
      freeze: () => { frozen = true; circuits.forEach(c => { c.speed = 0; c.phase = 0.5; }); planes.forEach(p => { p.t = 0.8; }); }};
    host.pineSys3 = api;
    return api;
  }
