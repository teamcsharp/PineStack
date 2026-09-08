// Pine's image gallery, decoded in the desktop and sent through the existing
// bounded LCD frame transport. The device's Quanta avatars remain independent.
(function (root) {
  const refreshMs = 60000, transitionMs = 1200;
  const effects = ['dissolve', 'slide-left', 'slide-up', 'wipe'];

  function catalogue(payload) {
    const seen = new Set(), files = [];
    for (const row of Array.isArray(payload?.generations) ? payload.generations : []) {
      if (!row || !Array.isArray(row.files)) continue;
      // Match the gallery's paper classifier. A regenerated picture may retain
      // Gazette tags, so tags alone must never hide that ordinary picture.
      if (row.kind === 'paper' || row.model === 'gazette' ||
          String(row.tags || '').startsWith('gazette ') &&
          row.files.some(name => String(name).split('/').pop().startsWith('gazette-'))) continue;
      for (const name of row.files) {
        if (typeof name !== 'string' || name.length > 200 || name.includes('..') ||
            /[\\/\u0000-\u001f\u007f]/.test(name) || !/\.(png|jpe?g|webp)$/i.test(name) || seen.has(name)) continue;
        seen.add(name); files.push(name);
      }
    }
    return files;
  }

  async function decode(data, {width, height}) {
    const source = new Image();
    try {
      await new Promise((resolve, reject) => {
        source.onload = resolve; source.onerror = () => reject(new Error('Gallery image could not be decoded.'));
        source.src = data;
      });
      const scale = Math.min(1, width / source.naturalWidth, height / source.naturalHeight);
      const w = Math.max(1, Math.round(source.naturalWidth * scale));
      const h = Math.max(1, Math.round(source.naturalHeight * scale));
      if (typeof createImageBitmap === 'function') {
        return await createImageBitmap(source, {resizeWidth: w, resizeHeight: h, resizeQuality: 'medium'});
      }
      const surface = document.createElement('canvas'); surface.width = w; surface.height = h;
      surface.getContext('2d').drawImage(source, 0, 0, w, h);
      return surface;
    } finally { source.onload = null; source.onerror = null; source.src = ''; }
  }

  function create({get, loadImage, random = Math.random, now = Date.now, decodeImage = decode}) {
    if (typeof get !== 'function' || typeof loadImage !== 'function') throw new Error('Gallery requires the station image bridge.');
    let files = [], bag = [], current = null, upcoming = null, loading = false;
    let fetching = null, fetched = false, lastRefresh = -Infinity, retryLoadAt = 0;
    let width = 320, height = 240, lastTick = null, wasPaused = false, shownMs = 0;
    let transition = null, lastEffect = '', advance = false, destroyed = false, currentPainted = false;
    let error = '', imageError = '', revision = 0;
    const failed = new Map();
    const time = () => { const value = Number(now()); return Number.isFinite(value) ? value : Date.now(); };
    const index = count => Math.min(count - 1, Math.max(0, Math.floor((Number(random()) || 0) * count)));
    const close = row => {
      if (!row?.image) return;
      if (typeof row.image.close === 'function') row.image.close();
      else { row.image.width = 0; row.image.height = 0; }
    };
    function shuffle(rows) {
      const shuffled = rows.slice();
      for (let i = shuffled.length - 1; i > 0; i--) {
        const j = index(i + 1); [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
      }
      return shuffled;
    }
    const eligible = name => name !== current?.id && name !== upcoming?.id &&
      (!failed.has(name) || time() - failed.get(name) >= refreshMs);
    function candidate() {
      bag = bag.filter(name => files.includes(name) && eligible(name));
      if (!bag.length) bag = shuffle(files.filter(eligible));
      return bag.shift();
    }
    function prefetch() {
      if (destroyed || loading || upcoming || time() < retryLoadAt) return;
      const id = candidate();
      if (!id) return;
      loading = true;
      // One image request/decode at a time. A failed image is remembered for a
      // minute and the next attempt waits for a later draw, never a retry loop.
      Promise.resolve().then(() => loadImage('/api/generations/image/' + encodeURIComponent(id)))
        .then(data => decodeImage(data, {width, height}))
        .then(image => {
          const row = {id, image};
          if (!image || !(image.width > 0) || !(image.height > 0)) {
            close(row); throw new Error('Gallery image has no pixels.');
          }
          if (destroyed) { close(row); return; }
          failed.delete(id); imageError = ''; retryLoadAt = 0;
          if (!current) { current = row; currentPainted = false; shownMs = 0; revision++; }
          else upcoming = row;
        }).catch(reason => {
          if (destroyed) return;
          failed.set(id, time()); retryLoadAt = time() + 250;
          imageError = String(reason?.message || 'Gallery image unavailable.');
        }).finally(() => {
          loading = false;
          // The first successful load may immediately prepare the second slot.
          // Failures wait for draw() so even immediate 404s cannot spin.
          if (!destroyed && !imageError) prefetch();
        });
    }
    function refresh() {
      if (destroyed) return Promise.resolve();
      if (fetching) return fetching;
      if (time() - lastRefresh < refreshMs) return Promise.resolve();
      lastRefresh = time();
      fetching = Promise.resolve().then(() => get('/api/generations?limit=1000'))
        .then(payload => {
          if (destroyed) return;
          files = catalogue(payload); fetched = true; error = '';
          const names = new Set(files);
          for (const name of failed.keys()) if (!names.has(name)) failed.delete(name);
          if (upcoming && !transition && !names.has(upcoming.id)) { close(upcoming); upcoming = null; }
          bag = shuffle(files.filter(eligible));
          prefetch();
        }).catch(reason => { if (!destroyed) error = String(reason?.message || 'Gallery unavailable.'); })
        .finally(() => { fetching = null; });
      return fetching;
    }
    function next() {
      if (destroyed) return;
      advance = true; refresh(); prefetch();
    }
    function paint(ctx, row, w, h, dx = 0, dy = 0) {
      const scale = Math.min(w / row.image.width, h / row.image.height);
      const iw = row.image.width * scale, ih = row.image.height * scale;
      ctx.drawImage(row.image, (w - iw) / 2 + dx, (h - ih) / 2 + dy, iw, ih);
    }
    function draw(ctx, w, h, timestamp, {intervalSeconds = 8, paused = false} = {}) {
      width = Math.max(1, Math.round(Number(w) || 320)); height = Math.max(1, Math.round(Number(h) || 240));
      const stamp = Number.isFinite(Number(timestamp)) ? Number(timestamp) : time();
      const delta = lastTick === null || paused || wasPaused ? 0 : Math.max(0, stamp - lastTick);
      lastTick = stamp; wasPaused = paused;
      refresh(); prefetch();
      const interval = Math.max(3, Math.min(60, Number(intervalSeconds) || 8)) * 1000;
      if (current && !paused) {
        if (transition) transition.elapsed += delta;
        else if (currentPainted) shownMs += delta;
        if (!transition && upcoming && (advance || shownMs >= interval)) {
          const choices = effects.filter(effect => effect !== lastEffect);
          lastEffect = choices[index(choices.length)];
          transition = {effect: lastEffect, elapsed: 0}; advance = false;
        }
        if (transition && transition.elapsed >= transitionMs) {
          close(current); current = upcoming; upcoming = null;
          transition = null; shownMs = 0; revision++;
          prefetch();
        }
      }
      const progress = transition ? Math.min(1, Math.max(0, transition.elapsed / transitionMs)) : 0;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
      ctx.globalAlpha = 1; ctx.fillStyle = '#000'; ctx.fillRect(0, 0, width, height);
      if (current) {
        if (!transition || !upcoming) paint(ctx, current, width, height);
        else if (transition.effect === 'slide-left') {
          paint(ctx, current, width, height, -width * progress);
          paint(ctx, upcoming, width, height, width * (1 - progress));
        } else if (transition.effect === 'slide-up') {
          paint(ctx, current, width, height, 0, -height * progress);
          paint(ctx, upcoming, width, height, 0, height * (1 - progress));
        } else if (transition.effect === 'dissolve') {
          // Add two weighted images over black, including their letterboxes.
          // Source-over on two partial alphas would darken the outgoing image twice.
          ctx.globalAlpha = 1 - progress; paint(ctx, current, width, height);
          ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = progress;
          paint(ctx, upcoming, width, height);
        } else {
          paint(ctx, current, width, height);
          ctx.beginPath(); ctx.rect(0, 0, width * progress, height); ctx.clip();
          ctx.fillRect(0, 0, width, height);
          paint(ctx, upcoming, width, height);
        }
        currentPainted = true;
      }
      ctx.restore();
      const state = current ? 'ready' : error || imageError && !loading ? 'error' : loading || fetching || !fetched ? 'loading' : 'empty';
      return {state, imageId: current?.id || '', total: files.length,
        transition: transition?.effect || '', transitioning: !!transition,
        paintKey: current ? [current.id, upcoming && transition ? upcoming.id : '', revision, width, height,
          transition?.effect || '', transition ? Math.round(progress * 1000) : 'still'].join(':') : state,
        error: error || imageError};
    }
    function destroy() {
      destroyed = true; close(current); close(upcoming); current = null; upcoming = null;
      files = []; bag = []; failed.clear(); transition = null;
    }
    return {draw, next, refresh, destroy};
  }
  const api = {create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PineLcdGallery = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
