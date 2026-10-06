'use strict';
const api = window.audioMixer;
const rows = {};
let pending = {}, writing = false, reading = false, closed = false;
const status = document.getElementById('status');
function show(values) {
  for (const [key, row] of Object.entries(rows)) {
    if (Object.hasOwn(pending, key) || row.dragging) continue;
    const value = Number(values[key]);
    if (!Number.isFinite(value)) continue;
    row.input.value = String(Math.round(value * 100));
    row.output.textContent = Math.round(value * 100) + '%';
  }
}
async function flush() {
  if (writing || closed) return;
  writing = true;
  try {
    while (Object.keys(pending).length) {
      const values = pending; pending = {};
      try { show(await api.set(values)); status.textContent = ''; }
      catch (error) { status.textContent = error.message; }
    }
  } finally { writing = false; }
}
for (const [key, label] of Object.entries({ master: 'Master', voice: 'Voices', music: 'Music', sfx: 'SFX', video: 'Videos', pads: 'Pads' })) {
  const row = document.createElement('div'); row.className = 'level';
  const name = document.createElement('label'); name.textContent = label; name.htmlFor = key;
  const input = document.createElement('input'); input.type = 'range'; input.id = key;
  input.min = '0'; input.max = key === 'master' ? '100' : '200'; input.step = '1'; input.value = '100';
  const output = document.createElement('output'); output.htmlFor = key; output.textContent = '100%';
  rows[key] = { input, output, dragging: false };
  input.addEventListener('pointerdown', () => { rows[key].dragging = true; });
  const release = () => { rows[key].dragging = false; };
  input.addEventListener('pointerup', release); input.addEventListener('pointercancel', release); input.addEventListener('blur', release);
  input.addEventListener('input', () => {
    output.textContent = input.value + '%'; pending[key] = Number(input.value) / 100; flush();
  });
  row.append(name, input, output); document.getElementById('levels').append(row);
}
async function refresh() {
  if (writing || reading || closed) return;
  reading = true;
  try { const values = await api.get(); if (!writing) { show(values); status.textContent = ''; } }
  catch (error) { status.textContent = error.message; }
  finally { reading = false; }
}
document.getElementById('reset').onclick = () => {
  pending = Object.fromEntries(Object.keys(rows).map(key => [key, 1]));
  for (const row of Object.values(rows)) { row.input.value = '100'; row.output.textContent = '100%'; }
  flush();
};
document.getElementById('close').onclick = () => api.close();
document.addEventListener('keydown', event => { if (event.key === 'Escape') api.close(); });
const timer = setInterval(refresh, 1000);
window.addEventListener('beforeunload', () => { closed = true; clearInterval(timer); });
refresh();
