(function(root){'use strict';
const RHET_SPHERE_COL = {dj:'#5ec8ff',host:'#5ec8ff',cohost:'#7cff9b',third:'#ffd166',guest:'#ffd166',caller:'#ff8ad1'};
const RHET_STOP = new Set(("about all also and any are because been before being "
 +"but can cant come could did does doing dont down each even ever every for from "
 +"get gets getting give going gonna good got had has have having her here hers him "
 +"his how ill its ive just keep kind know let like made make many may maybe more "
 +"most much must need never new not now off one only other our out over own please "
 +"put really right said same say says see should show similar since some something "
 +"still such sure take tell than that the their them then there these they thing "
 +"things think this those through too try use used using very want was way well went "
 +"were what when where which while who why will with without wont would yeah yes yet "
 +"you your youre yours theyre thats were are our").split(" "));
root.PineRhetoricSphere={open:async({onClose}={})=>{
 const element=document.createElement('section');element.id='pineWin-sphere';element.className='pine-win pip-rhetoric-sphere';
 const head=document.createElement('header');head.className='pine-win-head';const title=document.createElement('b');title.textContent='Rhetoric Sphere';
 const label=document.createElement('label');label.className='rhetoric-word-control';label.textContent='Words ';
 const slider=document.createElement('input');slider.type='range';slider.min='20';slider.max='500';slider.step='10';slider.setAttribute('aria-label','Rhetoric Sphere word limit');
 let saved;try{saved=Number(localStorage.getItem('pineRhetoricWordLimit'));}catch{}let limit=Number.isFinite(saved)&&saved>=20?Math.max(20,Math.min(500,Math.round(saved/10)*10)):90;
 slider.value=String(limit);const output=document.createElement('output');output.textContent=String(limit);label.append(slider,output);
 const status=document.createElement('span');status.className='rhetoric-word-status';status.setAttribute('role','status');
 const closeButton=document.createElement('button');closeButton.type='button';closeButton.textContent='\u00d7';closeButton.setAttribute('aria-label','Close Rhetoric Sphere');
 head.append(title,label,status,closeButton);const host=document.createElement('div');host.className='pine-win-host';element.append(head,host);document.body.append(element);
 let closed=false,controller=null,shown=0,available=0,updateWords=()=>{};
 slider.addEventListener('input',()=>{limit=Number(slider.value);output.textContent=String(limit);try{localStorage.setItem('pineRhetoricWordLimit',String(limit));}catch{}updateWords();});
 const close=()=>{if(closed)return;closed=true;controller?.stop();element.remove();onClose?.();};closeButton.onclick=close;
 try{await rhetSphereBuild(host);}catch(error){if(!closed){host.textContent='Sphere unavailable: '+error.message;status.textContent='Unable to load';}}
 return {element,close,state:()=>({limit,shown,available})};
async function rhetSphereBuild(host) {
  const THREE = await root.pineToolsImport("/vendor/three.module.js");
  if (closed) return;
  await new Promise((d) => requestAnimationFrame(() => d()));
  if (closed) return;
  const T = (typeof MIND_THEMES !== "undefined"
             && MIND_THEMES[window.rhetVecTheme]) || { bg: 0x04060b,
                                                       fog: 0x04060b };
  const size = () => [Math.max(1, host.clientWidth || 480),
                      Math.max(1, host.clientHeight || 420)];
  let [width, height] = size();
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(T.fog, 0.011);
  const camera = new THREE.PerspectiveCamera(52, width / height, 0.1, 500);
  camera.position.set(0, 0, 40 / Math.min(1, width / height));
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height); renderer.setClearColor(T.bg, 1);
  host.appendChild(renderer.domElement);
  const group = new THREE.Group(); scene.add(group);
  // A faint wire shell to read the sphere the words ride on.
  group.add(new THREE.Mesh(new THREE.IcosahedronGeometry(13, 2),
    new THREE.MeshBasicMaterial({ color: (T.a || 0x2b5a7a), wireframe: true,
      transparent: true, opacity: 0.06 })));

  function makeTex(word, color) {
    const c = document.createElement("canvas"), x = c.getContext("2d");
    const fs = 64;
    x.font = "700 " + fs + "px system-ui,sans-serif";
    c.width = Math.ceil(x.measureText(word).width) + 26; c.height = fs + 22;
    x.font = "700 " + fs + "px system-ui,sans-serif";
    x.textBaseline = "middle"; x.shadowColor = color; x.shadowBlur = 16;
    x.fillStyle = color; x.fillText(word, 13, c.height / 2);
    const t = new THREE.CanvasTexture(c); t.needsUpdate = true;
    return { t, aspect: c.width / c.height };
  }

  const sprites = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  function rebuild(state) {
    const counts = new Map(), who = new Map();
    for (const turn of ((state && state.chat) || [])) {
      const w = turn.who;
      if (!RHET_SPHERE_COL[w]) continue;
      const found = String(turn.text || "").toLowerCase()
        .match(/[a-z][a-z'\-]{2,}/g);
      if (!found) continue;
      for (let word of found) {
        word = word.replace(/^['\-]+|['\-]+$/g, "");
        if (word.length < 3
            || (typeof RHET_STOP !== "undefined" && RHET_STOP.has(word))) continue;
        counts.set(word, (counts.get(word) || 0) + 1);
        const ww = who.get(word) || {}; ww[w] = (ww[w] || 0) + 1; who.set(word, ww);
      }
    }
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
    const maxN = top.length ? top[0][1] : 1;
    const seen = new Set();
    top.forEach(([word, n], i) => {
      seen.add(word);
      const ww = who.get(word) || {}; let dom = "dj", best = -1;
      for (const k in ww) if (ww[k] > best) { best = ww[k]; dom = k; }
      const color = RHET_SPHERE_COL[dom] || "#9fb";
      let sp = sprites.find((s) => s.userData.word === word);
      if (!sp) {
        const { t, aspect } = makeTex(word, color);
        sp = new THREE.Sprite(new THREE.SpriteMaterial(
          { map: t, transparent: true, depthWrite: false }));
        sp.userData = { word, aspect, color };
        group.add(sp); sprites.push(sp);
      } else if (sp.userData.color !== color) {
        const { t, aspect } = makeTex(word, color);
        sp.material.map.dispose(); sp.material.map = t;
        sp.userData.aspect = aspect; sp.userData.color = color;
      }
      const y = top.length > 1 ? 1 - (i / (top.length - 1)) * 2 : 0;
      const r = Math.sqrt(Math.max(0, 1 - y * y)), th = golden * i;
      sp.userData.base = new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r);
      sp.userData.phase = (word.length * 1.3) % 6.283;
      sp.userData.scale = 1.4 + 2.8 * Math.sqrt(n / maxN);
    });
    for (const s of sprites.slice()) {
      if (seen.has(s.userData.word)) continue;
      s.material.map.dispose(); s.material.dispose(); group.remove(s);
      sprites.splice(sprites.indexOf(s), 1);
    }
    shown = top.length; available = counts.size;
    status.textContent = top.length ? top.length + " of " + counts.size + " words" : "Waiting for dialogue words";
  }
  rebuild(root.djLastState);
  updateWords = () => rebuild(root.djLastState);
  const refresh = setInterval(() => {
    try { rebuild(root.djLastState); } catch (e) {}
  }, 4000);

  let spinY = 0.003, spinX = 0.0006, dragging = false, lastX = 0, lastY = 0;
  let frame = 0, tsec = 0;
  function down(e) { dragging = true; lastX = e.clientX; lastY = e.clientY;
                     host.style.cursor = "grabbing"; }
  function up() { dragging = false; host.style.cursor = "grab"; }
  function move(e) {
    if (!dragging) return;
    spinY = (e.clientX - lastX) * 0.004; spinX = (e.clientY - lastY) * 0.004;
    lastX = e.clientX; lastY = e.clientY;
  }
  function wheel(e) { e.preventDefault();
    camera.position.z = Math.max(16, Math.min(70,
      camera.position.z + Math.sign(e.deltaY) * 3)); }
  host.addEventListener("pointerdown", down);
  window.addEventListener("pointerup", up);
  host.addEventListener("pointermove", move);
  host.addEventListener("wheel", wheel, { passive: false });
  const resize = new ResizeObserver(() => {
    const [w, h] = size();
    if (w === width && h === height) return;
    camera.position.z *= Math.min(1, camera.aspect) / Math.min(1, w / h);
    [width, height] = [w, h]; camera.aspect = w / h;
    camera.updateProjectionMatrix(); renderer.setSize(w, h);
  });
  resize.observe(host);

  function tick() {
    frame = requestAnimationFrame(tick);
    if (document.hidden || !renderer.domElement.offsetParent) return;  // #745
    tsec += 0.016;
    if (!dragging) { spinY += (0.003 - spinY) * 0.02;
                     spinX += (0.0006 - spinX) * 0.02; }
    group.rotation.y += spinY; group.rotation.x += spinX;
    const R = 13;
    for (const s of sprites) {
      const b = s.userData.base; if (!b) continue;
      const u = 1 + Math.sin(tsec * 0.9 + s.userData.phase) * 0.15;  // undulate
      s.position.set(b.x * R * u, b.y * R * u, b.z * R * u);
      const sc = s.userData.scale || 2;
      s.scale.set(sc * (s.userData.aspect || 3), sc, 1);
    }
    renderer.render(scene, camera);
  }

  controller = {
    stop() {
      cancelAnimationFrame(frame); clearInterval(refresh); resize.disconnect();
      host.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      host.removeEventListener("pointermove", move);
      host.removeEventListener("wheel", wheel);
      scene.traverse((o) => {
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
        if (o.geometry) o.geometry.dispose();
      });
      renderer.dispose(); host.textContent = "";
    },
  };
  tick();
}

}};})(window);
