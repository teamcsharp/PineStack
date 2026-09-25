(function (root) {
  'use strict';
  var opened = null;
  function make(tag, cls, text) {
    var n = document.createElement(tag); n.className = cls || '';
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function command(label, icon, action) {
    var n = make('button', 'pav-icon'); n.type = 'button';
    n.title = label; n.setAttribute('aria-label', label);
    if (root.pineIcon) n.innerHTML = root.pineIcon(icon);
    else { n.setAttribute('data-icon', icon); n.textContent = label; }
    n.addEventListener('click', action); return n;
  }
  function mediaFile(row) {
    var files = (row && row.files || []).filter(function (f) { return typeof f === 'string'; });
    return files.find(function (f) { return /\.(mp4|webm|mov|m4v)$/i.test(f); })
      || files.find(function (f) { return /\.(png|jpe?g|webp|gif)$/i.test(f); }) || '';
  }
  function open(initial, gallery) {
    if (opened) opened();
    var veil = make('div', 'pine-voice-ad-popup'); veil.id = 'pineVoiceAdPopup';
    var box = make('section', 'pine-voice-ad-card');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', gallery ? 'Pine Box Gallery' : 'Pine Box generated ads');
    var head = make('header', 'pav-head'); head.appendChild(make('b', '', gallery ? 'Pine Box Gallery' : 'Your Pine Box ad is ready'));
    var position = make('span', 'pav-position'); head.appendChild(position);
    var rows = [], signatures = {}, index = 0, revision = 0, gone = false, references = {}, original = false, currentRow = '';
    var pendingRows = [];
    var cursor = '', loading = false, stripStart = 0, crawl = 0, pausedUntil = 0, loadFailed = false;
    var disposeMedia = function () {}, exportTimer = 0;
    var more = command('Load ten more items', 'c:add', function () { loadPage(10); });
    more.disabled = true;
    if (gallery) head.insertBefore(more, position);
    var posters = {}, posterQueue = [], posterActive = 0, posterObserver = null;
    function pumpPosters() {
      while (!gone && posterActive < 2 && posterQueue.length) {
        var item = posterQueue.shift();
        if (!item.image.isConnected) continue;
        posterActive++;
        (function (entry) {
          root.pineDesktop.get('/api/generations/poster-url/' + encodeURIComponent(entry.file)).then(function (got) {
            if (gone || !got.poster) return;
            posters[entry.file] = typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(got.poster) : got.poster;
            if (entry.image.isConnected) entry.image.src = posters[entry.file];
          }).catch(function () { /* The branded thumbnail remains available for missing sources. */ })
            .finally(function () { posterActive--; pumpPosters(); });
        }(item));
      }
    }
    var previous = command('Previous ad', 'c:caret--left', function () {
      if (index + 1 < rows.length) { index++; paint(); }
      else if (cursor || pendingRows.length) loadPage().then(function () { if (index + 1 < rows.length) { index++; paint(); } });
    });
    var next = command('Next ad', 'c:caret--right', function () { if (index > 0) { index--; paint(); } });
    head.appendChild(previous); head.appendChild(next); box.appendChild(head);
    var strip = make('div', 'pav-strip'); strip.setAttribute('aria-label', 'Generated media');
    if (gallery) box.appendChild(strip);
    var motion = command('Pause gallery scrolling', 'c:pause--filled', function () {
      motion.dataset.paused = motion.dataset.paused === 'yes' ? '' : 'yes';
      motion.title = motion.dataset.paused ? 'Resume gallery scrolling' : 'Pause gallery scrolling';
      motion.setAttribute('aria-label', motion.title);
      if (root.pineIcon) motion.innerHTML = root.pineIcon(motion.dataset.paused ? 'c:caret--right' : 'c:pause--filled');
    });
    if (gallery) head.appendChild(motion);
    ['pointerdown', 'wheel', 'focusin'].forEach(function (name) {
      strip.addEventListener(name, function () { pausedUntil = Date.now() + 5000; }, {passive:true});
    });
    var description = make('p', 'pav-description'); box.appendChild(description);
    var stage = make('div', 'pav-stage'); box.appendChild(stage);
    var modes = make('div', 'pav-modes'); modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', 'Video source');
    var generatedButton = make('button', '', 'Generated'), originalButton = make('button', '', 'Original');
    generatedButton.type = originalButton.type = 'button'; originalButton.disabled = true;
    modes.append(generatedButton, originalButton); box.appendChild(modes);
    generatedButton.addEventListener('click', function () { if (original) { original = false; paint(true); } });
    originalButton.addEventListener('click', function () { if (!original) { original = true; paint(true); } });
    var reprompt = make('form', 'pav-reprompt'); reprompt.hidden = true;
    var directionLabel = make('label', '', 'Direction'), direction = make('textarea');
    direction.rows = 3; direction.maxLength = 1800; direction.required = true; directionLabel.appendChild(direction);
    var speechLabel = make('label', '', 'Dialogue'), speech = make('textarea'); speech.rows = 2; speech.maxLength = 800; speechLabel.appendChild(speech);
    var submit = make('button', '', 'Send to H3'); submit.type = 'submit';
    reprompt.append(directionLabel, speechLabel, submit); box.appendChild(reprompt);
    var status = make('p', 'pav-status'); status.setAttribute('role', 'status'); box.appendChild(status);
    var actions = make('footer', 'pine-voice-ad-actions');
    var save = command('Save to PineBoxRecordings', 'c:save', saveCurrent);
    save.disabled = true;
    actions.appendChild(save);
    var promptAgain = make('button', 'pav-reprompt-button', 'Prompt original again');
    promptAgain.type = 'button'; promptAgain.title = 'Send the recorded original through H3 with a new direction';
    promptAgain.addEventListener('click', function () {
      reprompt.hidden = !reprompt.hidden; promptAgain.setAttribute('aria-expanded', String(!reprompt.hidden));
      if (!reprompt.hidden) { direction.focus(); reprompt.scrollIntoView({block:'nearest'}); }
    });
    promptAgain.disabled = true; promptAgain.setAttribute('aria-expanded', 'false'); actions.appendChild(promptAgain);
    reprompt.addEventListener('submit', function (event) {
      event.preventDefault();
      var row = rows[index], ref = row && references[row.prompt_id], current = revision;
      if (!ref || !ref.available || ref.kind !== 'video') return;
      var words = direction.value.trim(), dialogue = speech.value.trim();
      if (!words) { direction.focus(); return; }
      submit.disabled = true; status.textContent = 'Queuing a new take from the original...';
      var body = {mode:'reference',purpose:'parody_stinger',source:ref.id,source_type:ref.source_type,
        prompt:words + (dialogue ? '\nSpoken dialogue: ' + dialogue : ''),speech:dialogue,steps:row.steps || 4,
        frames:row.frames || 121,air_it:false,source_generation:row.source_generation || '',variant_of:row.prompt_id};
      ['trim_in_s','trim_out_s','at_share'].forEach(function (key) { if (typeof row[key] === 'number') body[key] = row[key]; });
      root.pineDesktop.post('/api/comfy/workshop', body).then(function (got) {
        if (gone || current !== revision) return;
        status.textContent = got && (got.queue_id || got.prompt_id) ? 'New take submitted to H3. The original is unchanged.' : 'No H3 job was confirmed.';
      }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Could not submit: ' + err.message; })
        .finally(function () { if (!gone && current === revision) submit.disabled = false; });
    });
    var external = make('a', 'pine-voice-ad-open', 'Open media'); external.target = '_blank'; external.rel = 'noopener';
    actions.appendChild(external); actions.appendChild(command('Close ad viewer', 'c:close--filled', close)); box.appendChild(actions);
    veil.appendChild(box); document.body.appendChild(veil);
    veil.addEventListener('click', function (e) { if (e.target === veil) close(); });
    var focusWas = document.activeElement;
    function keys(e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      if (e.key === 'Tab') {
        var controls = Array.from(box.querySelectorAll('button:not(:disabled),a[href],textarea')).filter(function (n) { return n.getClientRects().length; });
        var at = controls.indexOf(document.activeElement);
        if (controls.length && (at < 0 || (e.shiftKey ? at === 0 : at === controls.length - 1))) {
          e.preventDefault(); controls[e.shiftKey ? controls.length - 1 : 0].focus();
        }
      }
    }
    document.addEventListener('keydown', keys, true);
    function close() {
      gone = true; revision++; clearInterval(crawl); clearTimeout(exportTimer); disposeMedia(); veil.remove();
      if (posterObserver) posterObserver.disconnect(); posterQueue = [];
      document.removeEventListener('keydown', keys, true); opened = null;
      if (focusWas && focusWas.isConnected) focusWas.focus();
    }
    opened = close;
    function sourceUrl(file, thumb) {
      var url = '/api/generations/' + (thumb ? 'image/' : 'media/') + encodeURIComponent(file)
        + '?t=' + encodeURIComponent(signatures[file] || '') + (thumb ? '&w=160' : '');
      return typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(url)
        : (/^https?:$/.test(location.protocol) ? url : 'http://127.0.0.1:8096' + url);
    }
    function paintStrip(keepScroll) {
      if (!gallery || gone) return;
      var old = strip.scrollLeft;
      if (posterObserver) posterObserver.disconnect(); posterQueue = [];
      if (root.IntersectionObserver) posterObserver = new root.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          posterObserver.unobserve(entry.target);
          posterQueue.push({image:entry.target, file:entry.target.dataset.file});
        });
        pumpPosters();
      }, {root:strip, rootMargin:'160px'});
      strip.replaceChildren();
      rows.slice(stripStart, stripStart + 80).forEach(function (row, offset) {
        var at = stripStart + offset, file = mediaFile(row);
        var tile = make('button', 'pav-tile'); tile.type = 'button'; tile.title = file;
        tile.setAttribute('aria-label', file); tile.setAttribute('aria-pressed', String(at === index));
        var thumb = make('img'); thumb.alt = ''; thumb.loading = 'lazy';
        var photo = (row.files || []).find(function (f) { return /\.(png|jpe?g|webp|gif)$/i.test(f); });
        thumb.src = photo ? sourceUrl(photo, true) : posters[file] || root.__pineLogo;
        thumb.onerror = function () { thumb.onerror = null; thumb.src = root.__pineLogo; };
        tile.appendChild(thumb); tile.appendChild(make('span', '', /\.(mp4|webm|mov|m4v)$/i.test(file) ? 'Video' : 'Image'));
        tile.addEventListener('click', function () { index = at; pausedUntil = Date.now() + 5000; paint(true); });
        strip.appendChild(tile);
        if (!photo && !posters[file]) {
          thumb.dataset.file = file;
          if (posterObserver) posterObserver.observe(thumb);
          else posterQueue.push({image:thumb,file:file});
        }
      });
      strip.scrollLeft = keepScroll ? old : 0;
      pumpPosters();
    }
    function loadPage(count) {
      if (loading || gone) return Promise.resolve();
      count = count || 30; loading = true; more.disabled = true;
      var requestPage = pendingRows.length >= count || (rows.length && !cursor) ? Promise.resolve(null) : root.pineDesktop.get('/api/generations/history?limit=' + count + '&purpose=' + (gallery ? '' : 'voice_ad')
        + '&before=' + encodeURIComponent(cursor));
      return requestPage.then(function (payload) {
        if (gone) return;
        loadFailed = false;
        if (payload) { Object.assign(signatures, payload.sig || {}); cursor = payload.next || ''; }
        (payload && payload.generations || []).forEach(function (row) {
          var files = gallery ? (row.files || []).filter(function (f) { return /\.(mp4|webm|mov|m4v|png|jpe?g|webp|gif)$/i.test(f); }) : [mediaFile(row)];
          files.filter(Boolean).forEach(function (file) {
            if (!rows.concat(pendingRows).some(function (r) { return r.prompt_id === row.prompt_id && mediaFile(r) === file; })) pendingRows.push(Object.assign({},row,{files:[file]}));
          });
        });
        rows.push.apply(rows, pendingRows.splice(0, count));
        previous.disabled = index + 1 >= rows.length && !cursor && !pendingRows.length;
        position.textContent = (rows.length - index) + ' / ' + rows.length;
        paintStrip(true);
      }).catch(function (err) {
        loadFailed = true; status.textContent = 'Could not load gallery history: ' + err.message;
      }).finally(function () { loading = false; more.disabled = !cursor && !pendingRows.length; });
    }
    function watchExport(id, current) {
      exportTimer = setTimeout(function () {
        if (gone || current !== revision) return;
        root.pineDesktop.get('/api/export/courier/status/' + encodeURIComponent(id)).then(function (got) {
          if (gone || current !== revision) return;
          status.textContent = got.state === 'delivered' ? 'Saved to ' + got.destination
            : got.state === 'failed' ? 'Archive copy failed: ' + (got.why || 'destination unavailable')
              : 'Archive copy queued; waiting for the desktop courier.';
          if (got.state === 'pending') watchExport(id, current);
        }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Copy status unavailable: ' + err.message; });
      }, 2500);
    }
    function saveCurrent() {
      var row = rows[index], file = mediaFile(row), current = revision;
      if (!file) return;
      save.disabled = true; status.textContent = 'Preparing archive copy...';
      root.pineDesktop.post('/api/gallery/export', {prompt_id: row.prompt_id, file: file,
        scope: original ? 'original' : 'generated', destination: 'share', name: (original ? 'Original-' : '') + file.replace(/\.[^.]+$/, '')}).then(function (got) {
        if (gone || current !== revision) return;
        if (!got || !got.ok || !got.id) throw new Error('The archive copy was not confirmed');
        status.textContent = 'Archive copy queued for ' + got.destination;
        watchExport(got.id, current);
      }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Could not save: ' + err.message; })
        .finally(function () { if (!gone && current === revision) save.disabled = false; });
    }
    function paint(fromStrip) {
      var current = ++revision;
      disposeMedia(); disposeMedia = function () {}; clearTimeout(exportTimer); stage.replaceChildren();
      var row = rows[index], file = mediaFile(row), scene = null, frame = 0, timer = 0;
      if (currentRow !== row.prompt_id) {
        currentRow = row.prompt_id; original = false; reprompt.hidden = true; promptAgain.setAttribute('aria-expanded','false');
        direction.value = String(row.tags || row.request || '').slice(0,1800); speech.value = row.speech || ''; submit.disabled = false;
      }
      var reference = references[row.prompt_id];
      generatedButton.setAttribute('aria-pressed', String(!original)); originalButton.setAttribute('aria-pressed', String(original));
      originalButton.disabled = !reference || !reference.available;
      promptAgain.disabled = !reference || !reference.available || reference.kind !== 'video';
      originalButton.title = reference && !reference.available ? reference.reason || 'Original unavailable' : 'Original reference';
      if (!reference) root.pineDesktop.get('/api/comfy/workshop/reference/' + encodeURIComponent(row.prompt_id)).then(function (got) {
        references[row.prompt_id] = got;
        if (gone || current !== revision) return;
        originalButton.disabled = !got.available; promptAgain.disabled = !got.available || got.kind !== 'video';
        originalButton.title = got.available ? 'Original reference' : got.reason || 'Original unavailable';
      }).catch(function (err) { if (!gone && current === revision) originalButton.title = 'Reference lookup failed: ' + err.message; });
      if (gallery && !fromStrip && (index < stripStart || index >= stripStart + 80)) stripStart = Math.max(0, index - 10);
      paintStrip(!!fromStrip);
      previous.disabled = index + 1 >= rows.length && !cursor && !pendingRows.length; next.disabled = index === 0;
      position.textContent = (rows.length - index) + ' / ' + rows.length;
      description.textContent = String(row.request || row.tags || 'Pine Box ad');
      save.disabled = !file || !signatures[file]; status.textContent = '';
      if (!file) { status.textContent = 'This ad has no playable output file.'; external.removeAttribute('href'); return; }
      var base = sourceUrl(file, false);
      if (original && reference && reference.available) base = typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(reference.url) : reference.url;
      external.href = base;
      var canvas = make('canvas', 'pav-particles'); canvas.setAttribute('aria-hidden', 'true'); stage.appendChild(canvas);
      var play = make('button', 'pav-play'); play.type = 'button'; play.title = 'Play Pine Box ad'; play.setAttribute('aria-label', play.title);
      var logo = make('img', 'pav-logo'); logo.alt = 'Pine Box'; logo.src = root.__pineLogo || '/spark/asset/pinebox.png';
      play.appendChild(logo); stage.appendChild(play);
      var isVideo = original ? reference.kind === 'video' : /\.(mp4|webm|mov|m4v)$/i.test(file), media = make(isVideo ? 'video' : 'img', 'pav-media');
      media.style.visibility = 'hidden'; stage.appendChild(media);
      var waiting = true;
      function background(on) {
        waiting = on; canvas.hidden = !on; play.hidden = !on;
        if (scene) { if (on && !document.hidden) scene.start(); else scene.stop(); }
      }
      function reveal() {
        if (gone || current !== revision) return;
        clearTimeout(timer); media.style.visibility = 'visible'; background(false); status.textContent = '';
      }
      function failed(words) {
        if (gone || current !== revision) return;
        clearTimeout(timer); media.style.visibility = 'hidden'; background(true);
        play.disabled = false; play.title = 'Retry Pine Box ad'; play.setAttribute('aria-label', play.title);
        status.textContent = words;
      }
      function visibility() { if (scene) { if (waiting && !document.hidden) scene.start(); else scene.stop(); } }
      document.addEventListener('visibilitychange', visibility);
      if (root.PinePlexus) root.PinePlexus.create(canvas).then(function (made) {
        if (gone || current !== revision) { made.dispose(); return; }
        scene = made; visibility();
      }).catch(function () { /* The branded poster remains available without WebGL. */ });
      media.addEventListener('error', function () { failed('The ad could not be loaded or decoded. Tap the Pine Box logo to retry.'); });
      if (isVideo) {
        media.controls = true; media.playsInline = true; media.preload = 'auto'; media.poster = logo.src;
        media.addEventListener('loadeddata', function () {
          if (media.readyState >= 2 && media.videoWidth > 0) reveal();
        });
        media.addEventListener('playing', function () {
          if (media.requestVideoFrameCallback) frame = media.requestVideoFrameCallback(reveal);
          else if (media.readyState >= 2 && media.videoWidth > 0) reveal();
        });
        function startMedia() {
          if (!signatures[file]) { failed('Media access is unavailable. Close and reopen this ad to refresh its file link.'); return; }
          status.textContent = 'Loading video...'; play.disabled = true;
          clearTimeout(timer);
          if (!media.getAttribute('src') || media.error) { media.src = base; media.load(); }
          timer = setTimeout(function () { failed('No video frame arrived. Check the media file or tap to retry.'); }, 20000);
          Promise.resolve(media.play()).catch(function (err) {
            if (gone || current !== revision) return;
            if (err.name === 'NotAllowedError') {
              play.disabled = false;
              if (media.readyState >= 2 && media.videoWidth > 0) reveal();
            } else failed('Playback failed: ' + err.message);
          })
            .finally(function () { if (current === revision) play.disabled = false; });
        }
        play.addEventListener('click', startMedia);
        startMedia();
      } else {
        media.alt = 'Generated Pine Box ad'; media.addEventListener('load', reveal); media.src = base;
        play.addEventListener('click', function () { media.src = base; });
      }
      disposeMedia = function () {
        clearTimeout(timer); document.removeEventListener('visibilitychange', visibility);
        if (frame && media.cancelVideoFrameCallback) media.cancelVideoFrameCallback(frame);
        if (isVideo) { media.pause(); media.removeAttribute('src'); media.load(); }
        if (scene) scene.dispose();
      };
    }
    previous.disabled = true; next.disabled = true;
    status.textContent = 'Locating generated ads...';
    loadPage().then(async function () {
      if (gone) return;
      if (initial) {
        while (!gone && !loadFailed && (cursor || pendingRows.length) && !rows.some(function (r) { return r.prompt_id === initial.prompt_id; })) await loadPage();
        if (gone) return;
        index = rows.findIndex(function (r) { return r.prompt_id === initial.prompt_id; });
        if (index < 0) {
          index = 0; previous.disabled = true; next.disabled = true;
          if (!loadFailed) status.textContent = 'This ad is not in the completed media archive. Refresh to check again.';
          return;
        }
      }
      if (rows.length) paint(); else if (!loadFailed) status.textContent = 'No completed media in the gallery yet.';
      if (gallery) motion.focus();
    });
    actions.insertBefore(command('Refresh gallery', 'c:renew', function () {
      if (loading) return;
      cursor = ''; rows = []; pendingRows = []; index = 0; stripStart = 0;
      save.disabled = true;
      loadPage().then(function () { if (!gone && rows.length) paint(); });
    }), external);
    if (gallery) crawl = setInterval(function () {
      if (gone || document.hidden || motion.dataset.paused || Date.now() < pausedUntil || loading || loadFailed) return;
      strip.scrollLeft += 1;
      if (strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 3) {
        if (stripStart + 80 < rows.length) { stripStart += 40; paintStrip(false); }
        else if (cursor || pendingRows.length) loadPage();
        else { stripStart = 0; paintStrip(false); }
      }
    }, 40);
  }
  root.PineAdViewer = {open: open, openGallery: function () { open(null, true); }, close: function () { if (opened) opened(); }, mediaFile: mediaFile};
  if (typeof module !== 'undefined') module.exports = root.PineAdViewer;
}(typeof window !== 'undefined' ? window : globalThis));
