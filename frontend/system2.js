/* A script first, with diagnostics available on demand. No invented execution. */
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const clock = value => new Date(value * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
const duration = value => `${Math.floor(Math.max(0, value) / 60)}m ${Math.round(Math.max(0, value) % 60)}s`;
const json = value => JSON.stringify(value, null, 2);
const query = args => new URLSearchParams(args).toString();

function save(name, value, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([value], {type}));
  const a = el('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function button(text, action, cls) {
  const node = el('button', text, cls); node.type = 'button';
  node.addEventListener('click', action); return node;
}

function block(title, value, open = false) {
  const details = el('details'); details.open = open;
  details.append(el('summary', title), el('pre', typeof value === 'string' ? value : json(value)));
  return details;
}

export function scriptText(data) {
  return (data.slots || []).map(slot => `${clock(slot.start)} ${slot.kind}\n\n` +
    ((slot.performances || []).map(p => p.script).join('\n\n') || 'No complete performance is staged.') +
    (slot.drafts || []).map(p => '\n\nDRAFT — not staged\n' + p.script).join('')).join('\n\n──────────\n\n');
}

async function assembly(container, trace) {
  const stages = [];
  if (trace.source?.script_plain || trace.source?.swaths) stages.push(['Source', 0x8ac6ac]);
  if (trace.source?.desk || trace.calls?.length) stages.push(['Writing', 0x87bfff]);
  if (trace.source?.script_tinted || trace.source?.tint || trace.source?.tint_report) stages.push(['Tint & checks', 0xc4a1ee]);
  if (trace.lines?.some(line => line.audio_hash)) stages.push(['Recorded take', 0xe7bf78]);
  container.append(el('p', 'Assembly replay from retained evidence. Select a stage to inspect it.'));
  const status = el('p', '', 's2-muted');
  const tabs = el('div', undefined, 's2-actions');
  const content = el('pre');
  const explain = index => {
    const label = stages[index][0]; status.textContent = label;
    content.textContent = json(label === 'Source' ? {script_plain: trace.source?.script_plain, swaths: trace.source?.swaths} :
      label === 'Writing' ? {desk: trace.source?.desk, calls: trace.calls} :
      label === 'Tint & checks' ? {script_tinted: trace.source?.script_tinted, report: trace.source?.tint || trace.source?.tint_report} : trace.lines);
  };
  stages.forEach(([label], i) => tabs.append(button(label, () => explain(i))));
  container.append(tabs, status, content);
  if (!stages.length) { status.textContent = 'No assembly stages were retained.'; return () => {}; }
  explain(0);
  let renderer, raf = 0, disposed = false, observer;
  const geometries = [], materials = [];
  try {
    const THREE = await import('/vendor/three.module.js');
    if (!container.isConnected) return () => {};
    const canvas = el('div', undefined, 's2-canvas'); container.insertBefore(canvas, tabs);
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5)); canvas.append(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-5, 5, 1.6, -1.6, .1, 20); camera.position.z = 8;
    const nodes = stages.map(([label, color], index) => {
      const geometry = new THREE.IcosahedronGeometry(.38, 1); geometries.push(geometry);
      const material = new THREE.MeshBasicMaterial({color, wireframe: true}); materials.push(material);
      const node = new THREE.Mesh(geometry, material);
      node.position.x = (index - (stages.length - 1) / 2) * 2.1; scene.add(node); return node;
    });
    const path = new THREE.BufferGeometry().setFromPoints(nodes.map(node => node.position)); geometries.push(path);
    const pathMaterial = new THREE.LineBasicMaterial({color: 0x64727b}); materials.push(pathMaterial);
    scene.add(new THREE.Line(path, pathMaterial));
    const packetGeometry = new THREE.SphereGeometry(.09, 10, 8); geometries.push(packetGeometry);
    const packetMaterial = new THREE.MeshBasicMaterial({color: 0xffffff}); materials.push(packetMaterial);
    const packet = new THREE.Mesh(packetGeometry, packetMaterial); scene.add(packet);
    const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
    renderer.domElement.addEventListener('click', event => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObjects(nodes)[0]; if (hit) explain(nodes.indexOf(hit.object));
    });
    const resize = () => renderer?.setSize(Math.max(240, canvas.clientWidth), 150, false);
    observer = new ResizeObserver(resize); observer.observe(canvas); resize();
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const frame = at => {
      if (disposed || !container.isConnected) return;
      const t = reduced ? 0 : (at / 6000) % 1;
      packet.position.x = nodes[0].position.x + t * (nodes.at(-1).position.x - nodes[0].position.x);
      nodes.forEach(node => { node.rotation.y = reduced ? 0 : at / 5000; });
      renderer.render(scene, camera);
      if (!reduced) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
  } catch {
    container.append(el('p', '3D rendering is unavailable here. The stage buttons show the same retained evidence.', 's2-muted'));
  }
  return () => { disposed = true; cancelAnimationFrame(raf); observer?.disconnect(); geometries.forEach(g => g.dispose());
    materials.forEach(m => m.dispose()); renderer?.dispose(); renderer?.domElement.remove(); };
}

export async function mount(root, {request, onClose} = {}) {
  request ||= async (path, options = {}) => {
    const key = localStorage.getItem('sparkAgentKey') || localStorage.getItem('pineboxApiKey') || localStorage.getItem('apiKey') || '';
    const response = await fetch(path, {...options, headers: {...options.headers,
      ...(key ? {Authorization: 'Bearer ' + key} : {}), ...(options.body ? {'Content-Type': 'application/json'} : {})}});
    const data = await response.json(); if (!response.ok) throw Error(data.detail || response.statusText); return data;
  };
  root.classList.add('s2');
  let alive = true, state, hourId = '', focusedSlot = '', polling = false;
  const cleanups = new Set(), archives = new Map();
  // #1069: the orchestrator's own account of every road - what it owes,
  // what it holds, why a segment is short and what it decided about it -
  // read once a minute and quoted on each segment card instead of a canned
  // sentence.
  let logic = null, logicAt = 0;
  async function loadLogic() {
    if (Date.now() - logicAt < 60000) return logic;
    try { logic = await request('/api/orchestrator/logic'); logicAt = Date.now(); }
    catch (error) { logicAt = Date.now() - 45000; }
    return logic;
  }
  function road(slot) {
    const roads = logic?.roads || {};
    return roads[slot.kind] || roads[slot.slot_kind] || null;
  }
  function explain(slot) {
    const missing = Number(slot.debt_seconds) > 0 && !slot.non_dialogue;
    const r = road(slot);
    const parts = [];
    if (slot.non_dialogue) return 'Music owns this slot; the selected record is queued when the entry starts.';
    if (missing) parts.push(`${duration(slot.debt_seconds)} of this segment has no complete, verified, unique recording staged for it.`);
    else parts.push('Required recordings are reserved for this occurrence.');
    if (!r) { parts.push('The orchestrator has not reported on this road yet.'); return parts.join(' '); }
    if (r.task?.why) parts.push(`The desk on the ${r.label || slot.kind} road: ${r.task.why}.`);
    else if (Number(r.uncovered) > 0) parts.push(`${duration(r.uncovered)} on the ${r.label || slot.kind} road is uncovered across the coming hours; ${duration(r.held)} is held against ${duration(r.owed)} owed.`);
    else parts.push(`The ${r.label || slot.kind} road holds ${duration(r.held)} against ${duration(r.owed)} owed over the coming hours.`);
    if (r.judgment?.lesson) parts.push(`Standing judgment: ${String(r.judgment.lesson).trim()}`);
    if (Number(r.learning?.miss_streak) > 0) parts.push(`This road has missed its target ${r.learning.miss_streak} closed hour(s) running; attainment ${Math.round((r.learning.attainment_ema || 0) * 100)}%, so it is asked for ${r.learning.factor || 1}x.`);
    return parts.join(' ');
  }
  const heading = el('header'); heading.append(el('h1', 'System2'));
  const subtitle = el('p', 'The hourly plan, its scripts, and the work still owed.', 's2-muted');
  const actions = el('div', undefined, 's2-actions');
  const engine = el('select'); engine.setAttribute('aria-label', 'Scheduler');
  [['legacy', 'Original scheduler'], ['system2', 'System2 scheduler']].forEach(([value, label]) => {
    const option = el('option', label); option.value = value; engine.append(option);
  });
  // #1070: the two coexistence dials. Fallback lets the original chain serve
  // an entry System2 has nothing verified for; legacy keepers keep the
  // original writers filling the common inventory System2 plans over.
  const toggle = (label, key) => {
    const row = el('label', label, 's2-toggle'); const input = el('input'); input.type = 'checkbox';
    row.prepend(input); input.addEventListener('change', async () => {
      input.disabled = true;
      try { await request('/api/system2/settings', {method: 'POST', body: json({[key]: input.checked})}); await refresh(); }
      catch (error) { report(error); input.checked = !input.checked; }
      finally { input.disabled = false; }
    });
    return {row, input};
  };
  const fallbackToggle = toggle('Original chain covers an empty entry', 'fallback');
  const keepersToggle = toggle('Original writers keep filling the inventory', 'legacy_keepers');
  const hourSelect = el('select'); hourSelect.setAttribute('aria-label', 'Broadcast hour');
  const message = el('p', '', 's2-status'); message.setAttribute('role', 'status');
  const summary = el('div', undefined, 's2-summary');
  const board = el('div', undefined, 's2-board');
  const paper = el('section', undefined, 's2-paper');
  const diagnostics = el('details'); diagnostics.append(el('summary', 'Orchestrator work and capacity'));
  const diagnosticBody = el('pre'); diagnostics.append(diagnosticBody);
  const events = el('details'); events.append(el('summary', 'Call-ins, guests, station events, music requests and plot beats'));
  const form = el('form', undefined, 's2-event-form');
  const eventKind = el('select'); eventKind.setAttribute('aria-label', 'Event type');
  [['call_in', 'Call-in'], ['station_event', 'Station event'], ['guest', 'Guest speaker'],
   ['music_request', 'Music request'], ['plotline', 'Plot beat']].forEach(([value, label]) => {
    const option = el('option', label); option.value = value; eventKind.append(option);
  });
  const labelInput = (label, tag = 'input') => {
    const row = el('label', label); const input = el(tag); row.append(input); form.append(row); return input;
  };
  form.append(eventKind);
  const eventLabel = labelInput('Event title'); eventLabel.maxLength = 100;
  const eventAt = labelInput('Scheduled time (leave empty for the next available scene boundary)'); eventAt.type = 'datetime-local';
  const eventSeconds = labelInput('Duration in seconds'); eventSeconds.type = 'number'; eventSeconds.min = 15; eventSeconds.max = 600; eventSeconds.value = 90;
  const caller = labelInput('Caller name');
  const guest = labelInput('Saved guest', 'select'); guest.append(el('option', 'Choose a guest'));
  const trackId = labelInput('Music library track ID');
  const plotId = labelInput('Plot ID (use the same ID for each scheduled beat)');
  const brief = labelInput('Scene brief or caller’s message', 'textarea'); brief.rows = 4; brief.maxLength = 6000;
  const submit = el('button', 'Schedule event'); submit.type = 'submit'; form.append(submit);
  const eventList = el('div'); events.append(form, eventList);
  const eventFields = () => {
    caller.parentElement.hidden = eventKind.value !== 'call_in';
    guest.parentElement.hidden = eventKind.value !== 'guest';
    trackId.parentElement.hidden = eventKind.value !== 'music_request';
    plotId.parentElement.hidden = eventKind.value !== 'plotline';
    brief.parentElement.hidden = eventKind.value === 'music_request';
  };
  eventKind.addEventListener('change', eventFields); eventFields();
  const report = error => { message.textContent = String(error.message || error); message.classList.add('s2-error'); };
  const downloadHour = async format => {
    try { const data = await request('/api/system2/script?' + query({hour: hourId}));
      save('pinebox-hour.' + format, format === 'json' ? json(data) : scriptText(data), format === 'json' ? 'application/json' : 'text/plain');
    } catch (error) { report(error); }
  };
  actions.append(engine, fallbackToggle.row, keepersToggle.row, hourSelect, button('Refresh', () => refresh(true)), button('Download hour script', () => downloadHour('txt')),
                 button('Download hour diagnostics', () => downloadHour('json')),
                 button('Earlier hours', async () => {
                   try { const data = await request('/api/system2/hours');
                     for (const hour of data.hours || []) if (!state.hours.some(h => h.id === hour.id)) archives.set(hour.id, hour);
                     fillHours(); message.textContent = 'Retained hours are available in the broadcast hour selector.';
                   } catch (error) { report(error); }
                 }));
  if (onClose) actions.append(button('Close', onClose));
  heading.append(subtitle, actions); root.replaceChildren(heading, message, summary, events, diagnostics, board, paper);
  request('/api/dj/guests').then(data => {
    for (const saved of data.guests || []) { const option = el('option', saved.name); option.value = saved.id; guest.append(option); }
  }).catch(() => {});
  let eventIntent = null;
  form.addEventListener('submit', async event => {
    event.preventDefault(); submit.disabled = true;
    const body = {kind: eventKind.value, label: eventLabel.value, seconds: Number(eventSeconds.value),
      brief: brief.value, caller_name: caller.value, guest_id: guest.value,
      track_id: trackId.value, plot_id: plotId.value};
    if (eventAt.value) body.air_at = new Date(eventAt.value).getTime()/1000;
    const identity = json(body);
    if (!eventIntent || eventIntent.body !== identity) eventIntent = {body: identity,
      id: globalThis.crypto?.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2, '0')).join('')};
    body.request_id = eventIntent.id;
    try {
      await request('/api/system2/events', {method: 'POST', body: json(body)});
      eventIntent = null; message.textContent = 'Event saved. Preparation and audible delivery are shown separately.';
      await refresh();
    } catch (error) { report(error); }
    finally { submit.disabled = false; }
  });

  async function showScript(slot) {
    focusedSlot = slot.id;
    cleanups.forEach(fn => fn()); cleanups.clear(); paper.replaceChildren();
    paper.append(el('h2', `${clock(slot.start)} · ${slot.label || slot.kind}`));
    const scriptActions = el('div', undefined, 's2-actions');
    const script = {slots: [{...slot, performances: slot.allocations.map(a => a.candidate)}]};
    scriptActions.append(button('Download segment', () => save('pinebox-segment.txt', scriptText(script))),
      button('Download segment diagnostics', () => save('pinebox-segment.json', json(script), 'application/json')));
    paper.append(scriptActions);
    if (!slot.allocations.length) paper.append(el('p', slot.non_dialogue ? 'Music owns this slot. The selected record is queued when this entry starts.' :
      'No complete performance is staged. The slot stays on the plan; its missing content is still owed.'));
    for (const allocation of [...slot.allocations, ...(slot.drafts || []).map(candidate => ({candidate, draft: true}))]) {
      const candidate = allocation.candidate;
      paper.append(el('p', allocation.draft ? `Draft — not staged · ${candidate.id} · ${(candidate.why || candidate.blocked_reasons || []).join('; ')}` :
        `${duration(candidate.seconds)} recorded · ${candidate.id}`, 's2-muted'));
      for (const line of candidate.lines || []) {
        const row = el('article', undefined, 's2-line');
        row.append(el('b', line.who || line.voice || 'Speaker'), el('p', line.text));
        const detail = el('details', undefined, 's2-trace');
        detail.append(el('summary', 'How this line was built'));
        const inner = el('div'); detail.append(inner);
        let loaded = false, dispose, generation = 0;
        detail.addEventListener('toggle', async () => {
          const visit = ++generation;
          if (!detail.open) { if (dispose) { cleanups.delete(dispose); dispose(); } dispose = null; loaded = false; inner.replaceChildren(); return; }
          if (loaded) return; loaded = true; inner.textContent = 'Loading retained diagnostics…';
          try {
            const trace = await request('/api/system2/line?' + query({candidate: candidate.id, line: line.id}));
            if (!detail.open || !alive || !detail.isConnected || visit !== generation) return;
            inner.replaceChildren();
            trace.limitations?.forEach(text => inner.append(el('p', text, 's2-muted')));
            const controls = el('div', undefined, 's2-actions');
            controls.append(button('Download line', () => save('pinebox-line.txt', `${line.who || 'Speaker'}: ${line.text}\n`)),
              button('Download line diagnostics', () => save('pinebox-line.json', json(trace), 'application/json')));
            if (line.url) {
              const audio = el('a', 'Download recording'); audio.href = line.url; audio.download = line.name || 'pinebox-line.wav';
              controls.append(audio);
            }
            inner.append(controls);
            const visual = el('div'); inner.append(visual); dispose = await assembly(visual, trace);
            if (!detail.open || !alive || !detail.isConnected || visit !== generation) { dispose(); dispose = null; return; }
            cleanups.add(dispose);
            inner.append(block('Source, transformations and checks', trace.source),
              block('Preparation jobs and observed events', trace.builds || []),
              block('Provider requests and responses for this scene', trace.calls), block('Recording evidence', trace.lines));
          } catch (error) { inner.textContent = error.message; }
        });
        row.append(detail); paper.append(row);
      }
    }
  }

  function paint() {
    const hour = state.hours.find(h => h.id === hourId) || archives.get(hourId) || state.hours[0];
    if (!hour) { board.textContent = 'The first plan is being assembled.'; return; }
    hourId = hour.id; hourSelect.value = hourId;
    const ready = hour.slots.filter(s => s.allocations.length || s.non_dialogue).length;
    summary.replaceChildren(el('strong', `${ready} / ${hour.slots.length} segments have a performance or music instruction`),
      el('span', `${duration(hour.ready_seconds)} recorded · ${duration(hour.debt_seconds)} still owed`),
      el('span', `Dialogue repeat window: 1 hour · ${state.paused ? 'Broadcast paused' : state.on ? 'Broadcast on' : 'Station off'}`));
    diagnosticBody.textContent = json({worker: state.work, errors: state.errors, inventory: state.inventory,
      jobs: state.jobs,
      explanation: 'Bars use specific recordings assigned exclusively to this slot. Missing content remains debt. Sending a clip does not count as heard.'});
    eventList.replaceChildren();
    for (const event of state.events || []) {
      const row = el('article', undefined, 's2-slot');
      row.append(el('h3', event.payload.label || event.kind.replaceAll('_', ' ')),
        el('p', `${event.payload.timing === 'asap' ? 'Next available scene after preparation' : clock(event.payload.air_at)} · ${event.state}${event.result?.heard ? ' · confirmed heard' : ''}`),
        block('Event details', event));
      const plan = (state.event_plans || []).find(p => p.id === 'event-' + event.id);
      if (plan?.slots?.[0]) row.append(button('Review event script', () => showScript(plan.slots[0])));
      eventList.append(row);
    }
    board.replaceChildren();
    for (const slot of hour.slots) {
      const card = el('article', undefined, 's2-slot');
      card.append(el('h3', `${clock(slot.start)} · ${slot.label || slot.kind}`));
      const bar = el('progress'); bar.max = slot.coverage_mode === 'one_performance' ? 1 : slot.target_seconds || 1;
      bar.value = slot.non_dialogue ? 1 : slot.coverage_mode === 'one_performance' ? (slot.allocations.length ? 1 : 0) : slot.ready_seconds;
      bar.setAttribute('aria-label', 'Recorded content for this segment'); card.append(bar);
      card.append(el('p', slot.non_dialogue ? 'Record instruction scheduled' :
        slot.coverage_mode === 'one_performance' ? `${duration(slot.ready_seconds)} staged · ${slot.allocations.length ? 'one performance assigned' : 'one performance needed'}` :
        `${duration(slot.ready_seconds)} staged · ${duration(slot.debt_seconds)} missing`));
      if (slot.heard_seconds) card.append(el('p', `${duration(slot.heard_seconds)} confirmed heard`));
      card.append(button('Review script', () => showScript(slot)), block('Orchestrator explanation and segment brief', {
        status: slot.status, deadline: new Date(slot.deadline * 1000).toLocaleString(),
        prompt: slot.prompt, required_seconds: slot.target_seconds, recorded_seconds: slot.ready_seconds,
        heard_seconds: slot.heard_seconds, missing_seconds: slot.debt_seconds,
        candidates: slot.allocations.map(a => a.candidate.id),
        why: explain(slot),
        road: road(slot) ? {label: road(slot).label, owed_seconds: road(slot).owed, held_seconds: road(slot).held,
          uncovered_seconds: road(slot).uncovered, write_cost_seconds: road(slot).cost,
          miss_streak_hours: road(slot).learning?.miss_streak, attainment: road(slot).learning?.attainment_ema,
          judgment: road(slot).judgment?.lesson, desk_task: road(slot).task} : 'not reported yet'}));
      card.append(el('p', explain(slot), 's2-muted'));
      board.append(card);
    }
    // Polls leave the open script and its inspection trays undisturbed.
    if (!focusedSlot) showScript(hour.slots.find(s => s.start <= Date.now()/1000 && s.deadline > Date.now()/1000) || hour.slots[0]);
  }

  function fillHours() {
    hourSelect.replaceChildren();
    [...state.hours, ...[...archives.values()].filter(h => !state.hours.some(current => current.id === h.id))].forEach(h => {
      const option = el('option', new Date(h.start * 1000).toLocaleString()); option.value = h.id; hourSelect.append(option);
    });
    hourSelect.value = hourId || state.hours[0]?.id || '';
  }

  async function refresh(force = false) {
    if (polling || !alive) return;
    polling = true;
    try {
      state = await request('/api/system2/status'); if (!alive) return;
      await loadLogic(); if (!alive) return;
      engine.value = state.config.engine;
      fallbackToggle.input.checked = state.config.fallback !== false;
      keepersToggle.input.checked = state.config.legacy_keepers !== false;
      fillHours();
      message.classList.remove('s2-error'); message.textContent = state.enabled
        ? ('System2 drives the hour: it stages verified performances and dispatches them on its own clock'
           + (state.config.fallback !== false ? '; the original chain serves any entry it has nothing verified for' : '; an entry it has nothing verified for stays music-only')
           + (state.config.legacy_keepers !== false ? '. The original writers keep filling the inventory it plans over.' : '. Only System2 prepares.'))
        : 'System2 is planning alongside the original scheduler. Select System2 to use it.';
      paint();
      if (force && focusedSlot) { const slot = [...state.hours, ...(state.event_plans || []), ...archives.values()].flatMap(h => h.slots || []).find(s => s.id === focusedSlot); if (slot) showScript(slot); }
    } catch (error) { report(error); }
    finally { polling = false; }
  }
  engine.addEventListener('change', async () => {
    engine.disabled = true;
    try { await request('/api/system2/settings', {method: 'POST', body: json({engine: engine.value})}); await refresh(); }
    catch (error) { report(error); engine.value = state?.config.engine || 'legacy'; }
    finally { engine.disabled = false; }
  });
  hourSelect.addEventListener('change', async () => {
    const selected = hourSelect.value;
    try {
      if (!state.hours.some(h => h.id === selected)) archives.set(selected, await request('/api/system2/hour?' + query({hour: selected})));
      hourId = selected; focusedSlot = ''; paint();
    } catch (error) { report(error); }
  });
  await refresh();
  const timer = alive ? setInterval(() => { if (!document.hidden) refresh(); }, 15000) : null;
  return {dispose() { alive = false; clearInterval(timer); cleanups.forEach(fn => fn()); root.replaceChildren(); }};
}

export async function openSystem2({request, onClose} = {}) {
  const backdrop = el('div', undefined, 's2-backdrop');
  const root = el('section'); root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', 'System2 hourly scripts'); backdrop.append(root); document.body.append(backdrop);
  const before = document.activeElement; let view, closed = false;
  const close = () => { if (closed) return; closed = true; view?.dispose(); backdrop.remove(); document.removeEventListener('keydown', key); before?.focus?.(); onClose?.(); };
  const key = event => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', key);
  backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });
  view = await mount(root, {request, onClose: close});
  if (closed) view.dispose(); else root.querySelector('button')?.focus();
  return {element: backdrop, close};
}
