(function(root){'use strict';
root.PineBroadcastWordCloud={open:async({request,onClose}={})=>{
 const element=document.createElement('section');element.id='pineWin-cloud';element.className='pine-win pip-broadcast-cloud';
 const head=document.createElement('header');head.className='pine-win-head';const title=document.createElement('b');title.textContent='Word Cloud';const close=document.createElement('button');close.textContent='×';close.title='Close Word Cloud';head.append(title,close);
 const host=document.createElement('div');host.className='pine-win-host';const status=document.createElement('span');status.className='broadcast-cloud-status';head.insertBefore(status,close);element.append(head,host);document.body.append(element);
 let cloud=null,closed=false,pending=false,timer=0,since=0;const model=root.PineBroadcastWords.create();
 async function cloudWords(){const now=Date.now()/1000,data=await request('/api/airlog?since='+Math.max(1,since||now-172800)+'&until='+now+'&most=5000');if(closed)return [];model.ingest(data.rows,now);since=now-30;return model.ranked(260,now);}
 function cloudStatus(words,error){const state=model.state();status.textContent=error?'Broadcast history temporarily unavailable':state.total+' spoken words · '+state.distinct+' distinct';}
 function cloudSprite(THREE, word, weight, heat) {
  if (heat === undefined) heat = weight;
  const size = 64;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const font = "600 " + size + "px system-ui, -apple-system, sans-serif";
  ctx.font = font;
  canvas.width = Math.ceil(ctx.measureText(word).width) + 28;
  canvas.height = Math.ceil(size * 1.5);
  ctx.font = font;                      // resizing the canvas resets the state
  ctx.textBaseline = "middle";
  // 196° cyan → 0° red. Cold = rare or long unsaid, hot = common or just
  // said, depending on where the recency slider sits.
  const hue = 196 - heat * 196;
  const sat = 30 + heat * 62;          // oldest words wash out toward white
  ctx.shadowColor = "hsla(" + hue + ",100%,62%," + (0.35 + heat * 0.5) + ")";
  ctx.shadowBlur = 10 + heat * 24;
  ctx.fillStyle = "hsl(" + hue + "," + sat + "%," + (62 + heat * 22) + "%)";
  ctx.fillText(word, 14, canvas.height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture, transparent: true, depthWrite: false,
  }));
  const scale = 1.1 + weight * 4.2;
  sprite.scale.set(scale * canvas.width / canvas.height, scale, 1);
  sprite.userData.baseScale = sprite.scale.clone();
  return sprite;
}

// Fibonacci sphere: evenly spread, no clustering at the poles.
function cloudPlace(sprite, index, count, radius) {
  const y = count > 1 ? 1 - (index / (count - 1)) * 2 : 0;
  const ring = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = Math.PI * (3 - Math.sqrt(5)) * index;
  sprite.position.set(
    Math.cos(theta) * ring * radius, y * radius, Math.sin(theta) * ring * radius
  );
}

function cloudFill(words) {
 if(!cloud)return;const {THREE,group}=cloud;cloud.words=words;
 const kept=new Map(group.children.map(s=>[s.userData.word,s]));
 const top=Math.max(1,...words.map(w=>w.count)),radius=10+Math.min(8,words.length/24);
 for(let index=0;index<words.length;index++){
  const entry=words[index],weight=Math.sqrt(entry.count/top),heat=0.4*weight+0.6*entry.recency;
  let sprite=kept.get(entry.word);
  if(sprite){kept.delete(entry.word);const scale=1.1+weight*4.2;const image=sprite.material.map.image;sprite.userData.baseScale.set(scale*image.width/image.height,scale,1);}
  else {sprite=cloudSprite(THREE,entry.word,weight,heat);sprite.userData.word=entry.word;group.add(sprite);cloudPlace(sprite,index,words.length,radius*0.25);}
  sprite.userData.count=entry.count;
  const target=sprite.userData.target||new THREE.Vector3();const previous=sprite.position.clone();cloudPlace(sprite,index,words.length,radius);target.copy(sprite.position);sprite.position.copy(previous);sprite.userData.target=target;
 }
 for(const sprite of kept.values()){group.remove(sprite);sprite.material.map.dispose();sprite.material.dispose();}
}
async function buildCloud(hostArg) {
  const THREE = await window.pineToolsImport("/vendor/three.module.js");
  const host = hostArg || document.getElementById("cloudHost");

  // A host that was display:none a moment ago can still measure 0x0 here.
  // An aspect of 0/0 is NaN and renders nothing, with no error to see.
  await new Promise((done) => requestAnimationFrame(() => done()));
  const size = () => [
    Math.max(240, host.clientWidth || host.offsetWidth || 480),
    Math.max(200, host.clientHeight || host.offsetHeight || 320),
  ];

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x04060b, 0.026);
  let [width, height] = size();
  const camera = new THREE.PerspectiveCamera(52, width / height, 0.1, 400);
  camera.position.set(0, 0, 34);

  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
  renderer.setClearColor(0x04060b, 1);
  host.appendChild(renderer.domElement);

  const group = new THREE.Group();
  scene.add(group);

  const label = document.createElement("div");
  label.style.cssText = "position:absolute;pointer-events:none;padding:4px 8px;"
    + "border-radius:6px;background:#0b1220e6;color:#cfe6ff;font-size:12px;"
    + "display:none;z-index:2";
  host.appendChild(label);

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let hovered = null;
  let spinX = 0.0011, spinY = 0.0026;
  let dragging = false, lastX = 0, lastY = 0, frame = 0;

  function onPointerDown(event) {
    dragging = true; lastX = event.clientX; lastY = event.clientY;
    host.style.cursor = "grabbing";
  }
  function onPointerUp() { dragging = false; host.style.cursor = "grab"; }
  function onPointerMove(event) {
    const box = host.getBoundingClientRect();
    pointer.x = ((event.clientX - box.left) / box.width) * 2 - 1;
    pointer.y = -((event.clientY - box.top) / box.height) * 2 + 1;
    label.style.left = (event.clientX - box.left + 14) + "px";
    label.style.top = (event.clientY - box.top + 12) + "px";
    if (!dragging) return;
    spinY = (event.clientX - lastX) * 0.004;
    spinX = (event.clientY - lastY) * 0.004;
    lastX = event.clientX; lastY = event.clientY;
  }
  function onWheel(event) {
    event.preventDefault();
    camera.position.z = Math.max(12, Math.min(70,
      camera.position.z + Math.sign(event.deltaY) * 2.5));
  }

  host.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("pointerup", onPointerUp);
  host.addEventListener("pointermove", onPointerMove);
  host.addEventListener("wheel", onWheel, {passive: false});

  const resize = new ResizeObserver(() => {
    const [w, h] = size();
    if (w === width && h === height) return;
    [width, height] = [w, h];
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
  resize.observe(host);

  function tick() {
    frame = requestAnimationFrame(tick);
    if (!dragging) {                       // drift back to a slow idle spin
      spinX += (0.0011 - spinX) * 0.02;
      spinY += (0.0026 - spinY) * 0.02;
    }
    group.rotation.y += spinY;
    group.rotation.x += spinX;

    // Glide toward the new ranking — words visibly shuffle as you talk.
    group.children.forEach((sprite) => {
      const target = sprite.userData.target;
      if (target) sprite.position.lerp(target, 0.06);
    });

    const t = performance.now() / 1000;
    cloud.pulse *= 0.96;
    const swell = 1 + Math.sin(t * 0.9) * 0.025 + cloud.pulse * 0.12;
    group.scale.set(swell, swell, swell);
    for (let i=0;i<group.children.length;i++) {
      const sprite=group.children[i], base=sprite.userData.baseScale;
      sprite.scale.copy(base).multiplyScalar((sprite===hovered?1.28:1)*(1 + Math.sin(t*1.25+i*0.7)*0.045));
      sprite.position.y += Math.sin(t*0.8+i*0.9)*0.009;
    }

    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(group.children, false)[0];
    const next = hit ? hit.object : null;
    if (next !== hovered) {
      if (hovered) hovered.scale.copy(hovered.userData.baseScale);
      hovered = next;
      if (hovered) {
        hovered.scale.copy(hovered.userData.baseScale).multiplyScalar(1.28);
        label.textContent = hovered.userData.word + " · "
          + hovered.userData.count + "×"
          + (hovered.userData.tail ? " · lands on " + hovered.userData.tail : "");
        label.style.display = "block";
      } else {
        label.style.display = "none";
      }
    }
    renderer.render(scene, camera);
  }

  cloud = {
    THREE, scene, camera, renderer, group, label, resize, host,
    words: [], pulse: 0,
    stop() {
      cancelAnimationFrame(frame);
      resize.disconnect();
      host.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointerup", onPointerUp);
      host.removeEventListener("pointermove", onPointerMove);
      host.removeEventListener("wheel", onWheel);
      group.children.slice().forEach((sprite) => {
        sprite.material.map.dispose();
        sprite.material.dispose();
      });
      renderer.dispose();
      host.textContent = "";
    },
  };

  // #813: the word fetch awaits the network — closing the cloud DURING
  // it nulls the global, and the resuming build then destructured null
  // ("Cannot destructure property 'THREE' of 'cloud'"). If the cloud we
  // built is no longer the live one, we were closed mid-load: tear our
  // renderer down quietly and stand down.
  const built = cloud;
  let words = [];
  try { words = await cloudWords(); } catch(e) { cloudStatus([], e.message); }
  if (cloud !== built) {
    try { built.stop(); } catch (error) { /* already gone */ }
    return;
  }
  cloudFill(words);
  cloudStatus(words);
  tick();
}


 async function refresh(){if(closed||pending)return;pending=true;const current=cloud;try{const words=await cloudWords();if(!closed&&cloud===current){const signature=words.map(w=>w.word+':'+w.count).join(',');if(signature!==cloud.signature){cloud.signature=signature;cloudFill(words);cloud.pulse=1;}cloudStatus(words);}}catch(e){if(!closed)cloudStatus([],e.message);}finally{pending=false;}}
 function destroy(){if(closed)return;closed=true;clearInterval(timer);cloud?.stop();cloud=null;element.remove();onClose?.();}
 close.onclick=destroy;
 try{await buildCloud(host);if(!closed)timer=setInterval(refresh,8000);}catch(e){status.textContent=e.message;}
 return {element,close:destroy,state:()=>model.state()};
}};})(window);
