/* Generated video ads: a body-level desk that can also run in the station browser. */
(function (root) {
  'use strict';

  var current = null;
  var threePromise = null;

  function el(tag, cls, words) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (words != null) node.textContent = String(words);
    return node;
  }

  function iconButton(ref, label, cls, handler) {
    var button = el('button', 'pga-icon ' + (cls || ''));
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.innerHTML = typeof root.pineIcon === 'function'
      ? (root.pineIcon(ref) || label) : label;
    button.addEventListener('click', handler);
    return button;
  }

  function api(method, route) {
    if (current && typeof current.request === 'function') {
      return Promise.resolve().then(function () {
        return current.request(route, method === 'post'
          ? {method: 'POST', body: '{}'} : {});
      });
    }
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge[method] === 'function') {
      try {
        return Promise.resolve(bridge[method](route, method === 'post' ? {} : undefined));
      } catch (error) {
        return Promise.reject(error);
      }
    }
    return root.fetch(route, {
      method: method.toUpperCase(),
      credentials: 'same-origin',
      headers: method === 'post' ? {'Content-Type': 'application/json'} : {},
      body: method === 'post' ? '{}' : undefined
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw new Error(body.error || body.message || ('Request failed (' + response.status + ')'));
        return body;
      });
    });
  }

  function mediaUrl(url) {
    if (!url) return '';
    if (typeof root.desktopMusicUrl === 'function') return root.desktopMusicUrl(url);
    return String(url);
  }

  function when(value) {
    if (!value) return '';
    var numeric = typeof value === 'number' || (typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value));
    var stamp = numeric ? Number(value) : null;
    var date = numeric ? new Date(stamp < 1e11 ? stamp * 1000 : stamp) : new Date(value);
    return isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  function duration(value) {
    var seconds = Number(value);
    if (!isFinite(seconds) || seconds < 0) return '--:--';
    return Math.floor(seconds / 60) + ':' + String(Math.floor(seconds % 60)).padStart(2, '0');
  }

  function errorText(error) {
    return String((error && error.message) || error || 'Unknown error');
  }

  function holdDuck(view) {
    if (view.duckApi || view.closed) return;
    var duck = root.PineDuck;
    if (!duck || typeof duck.hold !== 'function' || typeof duck.release !== 'function') return;
    duck.hold('gen-ads-preview', typeof duck.REPORT === 'number' ? duck.REPORT : 0.1, view.back);
    view.duckApi = duck;
  }

  function releaseDuck(view) {
    if (!view.duckApi) return;
    var duck = view.duckApi;
    view.duckApi = null;
    duck.release('gen-ads-preview');
  }

  function threeReady() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threePromise) return threePromise;
    threePromise = new Promise(function (resolve) {
      var tag = document.createElement('script');
      tag.src = typeof root.pineThreeUrl === 'function' ? root.pineThreeUrl()
        : '/vendor/three.min.js';
      tag.onload = function () { resolve(root.THREE || null); };
      tag.onerror = function () { resolve(null); };
      document.head.appendChild(tag);
    });
    return threePromise;
  }

  function stopFrames(view) {
    if (view.frame && root.cancelAnimationFrame) root.cancelAnimationFrame(view.frame);
    view.frame = 0;
    if (view.videoFrame && view.video.cancelVideoFrameCallback) {
      view.video.cancelVideoFrameCallback(view.videoFrame);
    }
    view.videoFrame = 0;
  }

  function stopScene(view) {
    if (view.probeTimer) clearTimeout(view.probeTimer);
    view.probeTimer = 0;
    stopFrames(view);
    if (view.readyFrame && view.video.cancelVideoFrameCallback) {
      view.video.cancelVideoFrameCallback(view.readyFrame);
    }
    view.readyFrame = 0;
    if (view.resizeObserver) view.resizeObserver.disconnect();
    view.resizeObserver = null;
    if (view.gl) {
      view.gl.texture.dispose();
      view.gl.mesh.geometry.dispose();
      view.gl.mesh.material.dispose();
      view.gl.renderer.dispose();
      view.gl.renderer.forceContextLoss && view.gl.renderer.forceContextLoss();
      view.gl.renderer.domElement.remove();
      view.gl = null;
    }
    view.stage.classList.remove('pga-webgl');
    view.stage.classList.remove('pga-native-ready');
  }

  function showNativeFrame(view, token) {
    if (view.closed || token !== view.mediaToken || !view.video.videoWidth
        || view.video.readyState < 2 || view.stage.classList.contains('pga-webgl')) return;
    view.stage.classList.add('pga-native-ready');
  }

  function watchFirstFrame(view) {
    if (!view.video.requestVideoFrameCallback || view.readyFrame
        || view.stage.classList.contains('pga-webgl')
        || view.stage.classList.contains('pga-native-ready')) return;
    var token = view.mediaToken;
    view.readyFrame = view.video.requestVideoFrameCallback(function () {
      view.readyFrame = 0;
      showNativeFrame(view, token);
    });
  }

  function draw(view) {
    if (!view.gl || view.closed || !view.video.videoWidth
        || (typeof view.video.readyState === 'number' && view.video.readyState < 2)) return;
    var gl = view.gl;
    var width = Math.max(1, view.stage.clientWidth);
    var height = Math.max(1, view.stage.clientHeight);
    try {
      if (gl.width !== width || gl.height !== height
          || gl.videoWidth !== view.video.videoWidth || gl.videoHeight !== view.video.videoHeight) {
        gl.renderer.setSize(width, height, false);
        var videoRatio = view.video.videoWidth / Math.max(1, view.video.videoHeight);
        var stageRatio = width / height;
        gl.mesh.scale.set(videoRatio > stageRatio ? 1 : videoRatio / stageRatio,
          videoRatio > stageRatio ? stageRatio / videoRatio : 1, 1);
        gl.width = width;
        gl.height = height;
        gl.videoWidth = view.video.videoWidth;
        gl.videoHeight = view.video.videoHeight;
      }
      gl.texture.needsUpdate = true;
      gl.renderer.render(gl.scene, gl.camera);
      if (!gl.proved && gl.probes < 8) {
        gl.probes += 1;
        var context = gl.renderer.getContext();
        var pixel = new Uint8Array(4);
        for (var i = 1; i <= 3; i += 1) {
          context.readPixels(Math.floor(context.drawingBufferWidth * i / 4),
            Math.floor(context.drawingBufferHeight / 2), 1, 1,
            context.RGBA, context.UNSIGNED_BYTE, pixel);
          if (pixel[0] + pixel[1] + pixel[2] > 12) {
            gl.proved = true;
            view.stage.classList.remove('pga-native-ready');
            view.stage.classList.add('pga-webgl');
            break;
          }
        }
        if (!gl.proved && gl.probes < 8 && view.video.paused && !view.probeTimer) {
          view.probeTimer = setTimeout(function () {
            view.probeTimer = 0;
            draw(view);
          }, 100);
        }
      }
    } catch (error) {
      stopScene(view);
    }
  }

  function scheduleFrame(view) {
    if (!view.gl || view.closed || view.video.paused || view.frame || view.videoFrame) return;
    if (typeof view.video.requestVideoFrameCallback === 'function') {
      view.videoFrame = view.video.requestVideoFrameCallback(function () {
        view.videoFrame = 0;
        draw(view);
        scheduleFrame(view);
      });
    } else if (root.requestAnimationFrame) {
      view.frame = root.requestAnimationFrame(function () {
        view.frame = 0;
        draw(view);
        scheduleFrame(view);
      });
    }
  }

  function startScene(view) {
    var token = view.mediaToken;
    threeReady().then(function (THREE) {
      if (view.closed || token !== view.mediaToken || !THREE) return;
      try {
        var renderer = new THREE.WebGLRenderer({alpha: false, antialias: false});
        renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2));
        var texture = new THREE.VideoTexture(view.video);
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        var scene = new THREE.Scene();
        var camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2);
        camera.position.z = 1;
        var mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2),
          new THREE.MeshBasicMaterial({map: texture}));
        scene.add(mesh);
        view.gl = {renderer: renderer, texture: texture, scene: scene, camera: camera,
          mesh: mesh, proved: false, probes: 0, width: 0, height: 0};
        view.stage.insertBefore(renderer.domElement, view.video);
        if (root.ResizeObserver) {
          view.resizeObserver = new root.ResizeObserver(function () { draw(view); });
          view.resizeObserver.observe(view.stage);
        } else {
          root.addEventListener('resize', view.onResize);
        }
        draw(view);
        scheduleFrame(view);
      } catch (error) {
        stopScene(view);
      }
    });
  }

  function updateTransport(view) {
    var video = view.video;
    view.play.title = video.paused ? 'Play ad' : 'Pause ad';
    view.play.setAttribute('aria-label', view.play.title);
    view.play.innerHTML = root.pineIcon
      ? root.pineIcon(video.paused ? 'c:caret--right' : 'c:pause--filled') : (video.paused ? 'Play' : 'Pause');
    view.mute.title = video.muted ? 'Unmute ad' : 'Mute ad';
    view.mute.setAttribute('aria-label', view.mute.title);
    view.mute.innerHTML = root.pineIcon
      ? root.pineIcon(video.muted ? 'c:volume--mute--filled' : 'c:volume--up--filled')
      : (video.muted ? 'Unmute' : 'Mute');
    var total = isFinite(video.duration) ? video.duration : Number(view.selected && view.selected.duration) || 0;
    view.seek.max = Math.max(1, Math.floor(total * 10));
    view.seek.value = Math.min(Number(view.seek.max), Math.floor((video.currentTime || 0) * 10));
    view.seek.disabled = !total;
    view.time.textContent = duration(video.currentTime || 0) + ' / ' + duration(total);
  }

  function renderHistory(view, row) {
    view.history.replaceChildren();
    var items = Array.isArray(row.history) ? row.history : [];
    view.historyCount.textContent = String(Number(row.air_count) || items.length);
    if (!items.length) {
      view.history.appendChild(el('p', 'pga-muted', 'No on-air plays recorded.'));
      return;
    }
    items.forEach(function (item) {
      var entry = el('li', 'pga-history-row');
      if (typeof item !== 'object' || !item) {
        entry.textContent = when(item);
      } else {
        var stamp = item.aired_at || item.at || item.started_at || item.created_at || item.timestamp;
        entry.appendChild(el('strong', '', when(stamp) || 'On air'));
        var detail = [item.program, item.booth, item.status || item.outcome].filter(Boolean).join(' / ');
        if (detail) entry.appendChild(el('span', '', detail));
      }
      view.history.appendChild(entry);
    });
  }

  function select(view, index, focus) {
    if (index < 0 || index >= view.rows.length || view.closed) return;
    var row = view.rows[index];
    var changed = !view.selected || String(view.selected.id) !== String(row.id)
      || view.selected.url !== row.url || view.selected.poster_url !== row.poster_url;
    view.index = index;
    view.selected = row;
    Array.prototype.forEach.call(view.feed.querySelectorAll('.pga-row'), function (node, i) {
      node.setAttribute('aria-selected', i === index ? 'true' : 'false');
      node.tabIndex = i === index ? 0 : -1;
    });
    var selectedNode = view.feed.querySelectorAll('.pga-row')[index];
    if (selectedNode) {
      selectedNode.scrollIntoView && selectedNode.scrollIntoView({block: 'nearest'});
      if (focus) selectedNode.focus();
    }
    view.name.textContent = row.name || 'Untitled ad';
    view.created.textContent = when(row.created_at) || 'Date unknown';
    view.prompt.textContent = row.prompt_id ? 'Prompt ' + row.prompt_id : 'No prompt ID';
    view.length.textContent = duration(row.duration);
    view.send.disabled = view.sending || row.id == null;
    renderHistory(view, row);
    if (changed) {
      releaseDuck(view);
      view.mediaToken += 1;
      stopScene(view);
      view.video.pause();
      view.video.removeAttribute('src');
      view.video.load();
      view.posterFallback = !row.poster_url;
      view.poster.hidden = false;
      view.poster.classList.toggle('pga-poster-icon', view.posterFallback);
      view.poster.src = mediaUrl(row.poster_url || '/spark/asset/pinebox.png');
      view.pictureMessage.textContent = row.url ? 'Loading video...' : 'Video file unavailable';
      view.pictureMessage.hidden = false;
      if (row.url) {
        view.video.src = mediaUrl(row.url);
        watchFirstFrame(view);
        view.video.load();
        startScene(view);
      }
    }
    updateTransport(view);
  }

  function renderFeed(view) {
    view.feed.replaceChildren();
    view.count.textContent = String(view.rows.length);
    if (!view.rows.length) {
      releaseDuck(view);
      view.mediaToken += 1;
      stopScene(view);
      view.video.pause();
      view.video.removeAttribute('src');
      view.video.load();
      view.selected = null;
      view.index = -1;
      view.feed.appendChild(el('p', 'pga-empty', 'No generated video ads yet.'));
      view.detail.hidden = true;
      view.placeholder.hidden = false;
      view.placeholder.textContent = 'New video ads will appear here.';
      return;
    }
    view.detail.hidden = false;
    view.placeholder.hidden = true;
    view.rows.forEach(function (row, index) {
      var button = el('button', 'pga-row');
      button.type = 'button';
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', 'false');
      button.tabIndex = -1;
      button.appendChild(el('span', 'pga-row-index', String(index + 1).padStart(2, '0')));
      var copy = el('span', 'pga-row-copy');
      copy.appendChild(el('strong', '', row.name || 'Untitled ad'));
      copy.appendChild(el('small', '', [duration(row.duration), when(row.created_at)].filter(Boolean).join(' / ')));
      button.appendChild(copy);
      button.appendChild(el('span', 'pga-row-airs', String(Number(row.air_count) || 0)));
      button.addEventListener('click', function () { select(view, index, true); });
      view.feed.appendChild(button);
    });
    var previous = view.selected && String(view.selected.id);
    var index = view.rows.findIndex(function (row) { return String(row.id) === previous; });
    select(view, index >= 0 ? index : 0, false);
  }

  function refresh(view) {
    if (view.closed) return Promise.resolve();
    var ticket = ++view.fetchToken;
    view.refresh.disabled = true;
    view.feedState.textContent = view.rows.length ? 'Refreshing...' : 'Loading video ads...';
    return api('get', '/api/gen-ads').then(function (body) {
      if (view.closed || ticket !== view.fetchToken) return;
      if (!body || !Array.isArray(body.rows)) throw new Error('The ad list response has no rows.');
      view.rows = body.rows.filter(function (row) { return row && row.id != null; });
      view.feedState.textContent = '';
      renderFeed(view);
    }).catch(function (error) {
      if (view.closed || ticket !== view.fetchToken) return;
      view.feedState.textContent = 'Could not load ads: ' + errorText(error);
      if (!view.rows.length) {
        view.feed.replaceChildren();
        view.detail.hidden = true;
        view.placeholder.hidden = false;
        view.placeholder.textContent = 'The ad list is unavailable. Refresh to try again.';
      }
    }).then(function () {
      if (!view.closed && ticket === view.fetchToken) view.refresh.disabled = false;
    });
  }

  function send(view) {
    if (!view.selected || view.sending) return Promise.resolve();
    var id = view.selected.id;
    view.sending = true;
    view.send.disabled = true;
    view.notice.textContent = 'Sending to booth...';
    view.notice.classList.remove('pga-error');
    return api('post', '/api/gen-ads/' + encodeURIComponent(id) + '/send').then(function (body) {
      if (view.closed) return;
      if (body && (body.ok === false || body.error)) throw new Error(body.error || body.message || 'The booth rejected this ad.');
      view.notice.textContent = 'Queued for booth.';
      return refresh(view);
    }).catch(function (error) {
      if (view.closed) return;
      view.notice.textContent = 'Could not send: ' + errorText(error);
      view.notice.classList.add('pga-error');
    }).then(function () {
      if (view.closed) return;
      view.sending = false;
      view.send.disabled = !view.selected;
    });
  }

  function close() {
    var view = current;
    if (!view) return;
    current = null;
    view.closed = true;
    view.fetchToken += 1;
    view.mediaToken += 1;
    root.removeEventListener('keydown', view.onKey);
    root.removeEventListener('resize', view.onResize);
    releaseDuck(view);
    stopScene(view);
    view.video.pause();
    view.video.removeAttribute('src');
    view.video.load();
    view.back.remove();
    if (view.returnFocus && view.returnFocus.isConnected) view.returnFocus.focus();
    if (view.onClose) view.onClose();
  }

  function open(options) {
    options = options || {};
    if (current) {
      current.closeButton.focus();
      return current.back;
    }
    var view = {rows: [], index: -1, selected: null, mediaToken: 0, fetchToken: 0,
      closed: false, sending: false, frame: 0, videoFrame: 0, readyFrame: 0,
      probeTimer: 0,
      duckApi: null, gl: null,
      request: options.request, onClose: options.onClose,
      returnFocus: document.activeElement};
    current = view;
    var back = view.back = el('div', 'pga-back');
    var dialog = el('section', 'pga-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', 'Generated video ads');
    back.appendChild(dialog);
    var header = el('header', 'pga-header');
    var heading = el('div', 'pga-heading');
    heading.appendChild(el('small', '', 'PINE BOX / PRODUCTION'));
    heading.appendChild(el('h2', '', 'Generated ads'));
    header.appendChild(heading);
    var actions = el('div', 'pga-header-actions');
    view.refresh = iconButton('c:renew', 'Refresh ads', '', function () { refresh(view); });
    view.closeButton = iconButton('c:close--filled', 'Close generated ads', '', close);
    actions.appendChild(view.refresh);
    actions.appendChild(view.closeButton);
    header.appendChild(actions);
    dialog.appendChild(header);

    var main = el('div', 'pga-main');
    var aside = el('aside', 'pga-feed-panel');
    var feedTitle = el('div', 'pga-feed-heading');
    feedTitle.appendChild(el('strong', '', 'All video ads'));
    view.count = el('span', 'pga-count', '0');
    feedTitle.appendChild(view.count);
    aside.appendChild(feedTitle);
    view.feedState = el('p', 'pga-feed-state');
    view.feedState.setAttribute('role', 'status');
    aside.appendChild(view.feedState);
    view.feed = el('div', 'pga-feed');
    view.feed.setAttribute('role', 'listbox');
    view.feed.setAttribute('aria-label', 'Generated video ads');
    aside.appendChild(view.feed);
    main.appendChild(aside);

    var content = el('div', 'pga-content');
    view.placeholder = el('p', 'pga-placeholder', 'Loading video ads...');
    content.appendChild(view.placeholder);
    view.detail = el('div', 'pga-detail');
    view.detail.hidden = true;
    var stage = view.stage = el('div', 'pga-stage');
    // PineDuck excludes sampler-marked media, so the preview keeps its own volume.
    var video = view.video = el('video', 'pga-video pb-sampler');
    video.preload = 'auto';
    video.playsInline = true;
    video.setAttribute('playsinline', '');
    video.setAttribute('aria-label', 'Selected generated video ad');
    stage.appendChild(video);
    view.poster = el('img', 'pga-poster pga-poster-icon');
    view.poster.alt = '';
    view.poster.setAttribute('aria-hidden', 'true');
    stage.appendChild(view.poster);
    view.pictureMessage = el('span', 'pga-picture-message', 'Loading video...');
    stage.appendChild(view.pictureMessage);
    view.detail.appendChild(stage);
    var transport = el('div', 'pga-transport');
    view.play = iconButton('c:caret--right', 'Play ad', '', function () {
      if (video.paused) {
        Promise.resolve(video.play()).catch(function (error) {
          view.pictureMessage.hidden = false;
          view.pictureMessage.textContent = 'Could not play video: ' + errorText(error);
        });
      } else video.pause();
    });
    transport.appendChild(view.play);
    view.seek = el('input', 'pga-seek');
    view.seek.type = 'range'; view.seek.min = '0'; view.seek.max = '1'; view.seek.value = '0';
    view.seek.setAttribute('aria-label', 'Seek through ad');
    view.seek.addEventListener('input', function () { video.currentTime = Number(view.seek.value) / 10; });
    transport.appendChild(view.seek);
    view.time = el('span', 'pga-time', '0:00 / --:--');
    transport.appendChild(view.time);
    view.mute = iconButton('c:volume--up--filled', 'Mute ad', '', function () {
      video.muted = !video.muted;
      updateTransport(view);
    });
    transport.appendChild(view.mute);
    view.detail.appendChild(transport);

    var facts = el('div', 'pga-facts');
    var identity = el('div', 'pga-identity');
    view.name = el('h3', '', ''); identity.appendChild(view.name);
    var meta = el('p', 'pga-meta');
    view.created = el('span'); view.length = el('span'); view.prompt = el('span');
    meta.appendChild(view.created); meta.appendChild(view.length); meta.appendChild(view.prompt);
    identity.appendChild(meta);
    facts.appendChild(identity);
    view.send = el('button', 'pga-send', 'Send to booth');
    view.send.type = 'button';
    view.send.title = 'Send selected ad to booth';
    view.send.addEventListener('click', function () { send(view); });
    facts.appendChild(view.send);
    view.detail.appendChild(facts);
    view.notice = el('p', 'pga-notice');
    view.notice.setAttribute('role', 'status');
    view.detail.appendChild(view.notice);
    var historyHead = el('div', 'pga-history-heading');
    historyHead.appendChild(el('h4', '', 'On-air history'));
    view.historyCount = el('span', 'pga-count', '0');
    historyHead.appendChild(view.historyCount);
    view.detail.appendChild(historyHead);
    view.history = el('ul', 'pga-history');
    view.detail.appendChild(view.history);
    content.appendChild(view.detail);
    main.appendChild(content);
    dialog.appendChild(main);
    back.addEventListener('click', function (event) { if (event.target === back) close(); });
    document.body.appendChild(back);

    view.poster.addEventListener('error', function () {
      if (!view.posterFallback) {
        view.posterFallback = true;
        view.poster.classList.add('pga-poster-icon');
        view.poster.src = mediaUrl('/spark/asset/pinebox.png');
      } else view.poster.hidden = true;
    });
    video.addEventListener('loadeddata', function () {
      view.pictureMessage.hidden = true;
      draw(view);
      watchFirstFrame(view);
      if (!video.requestVideoFrameCallback && video.duration > 0 && video.currentTime === 0) {
        try { video.currentTime = Math.min(0.04, video.duration / 2); } catch (error) { /* keep poster */ }
      }
      updateTransport(view);
    });
    video.addEventListener('error', function () {
      releaseDuck(view);
      stopFrames(view);
      view.pictureMessage.hidden = false;
      view.pictureMessage.textContent = 'Video could not be loaded.';
    });
    video.addEventListener('play', function () {
      holdDuck(view);
      watchFirstFrame(view);
      updateTransport(view);
      scheduleFrame(view);
    });
    video.addEventListener('pause', function () { releaseDuck(view); stopFrames(view); updateTransport(view); });
    video.addEventListener('ended', function () { releaseDuck(view); stopFrames(view); updateTransport(view); });
    video.addEventListener('timeupdate', function () {
      updateTransport(view);
    });
    video.addEventListener('seeked', function () {
      draw(view);
      if (!video.requestVideoFrameCallback && video.currentTime > 0)
        showNativeFrame(view, view.mediaToken);
    });
    video.addEventListener('loadedmetadata', function () { updateTransport(view); draw(view); });
    view.onResize = function () { draw(view); };
    view.onKey = function (event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key === 'Tab') {
        var focusable = dialog.querySelectorAll('button:not(:disabled), input:not(:disabled)');
        if (!focusable.length) return;
        var first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        return;
      }
      if (event.target && /INPUT|TEXTAREA/.test(event.target.tagName)) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault(); select(view, Math.min(view.rows.length - 1, view.index + 1), true);
      } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault(); select(view, Math.max(0, view.index - 1), true);
      } else if (event.key === ' ' && event.target === view.stage) {
        event.preventDefault(); if (video.paused) view.play.click(); else video.pause();
      }
    };
    root.addEventListener('keydown', view.onKey);
    var touchX = null;
    stage.addEventListener('touchstart', function (event) {
      touchX = event.touches.length === 1 ? event.touches[0].clientX : null;
    }, {passive: true});
    stage.addEventListener('touchend', function (event) {
      if (touchX == null || !event.changedTouches.length) return;
      var delta = event.changedTouches[0].clientX - touchX;
      touchX = null;
      if (Math.abs(delta) > 70) select(view, Math.max(0, Math.min(view.rows.length - 1,
        view.index + (delta < 0 ? 1 : -1))), false);
    }, {passive: true});
    view.closeButton.focus();
    refresh(view);
    return back;
  }

  root.PineGenAds = {open: open, close: close};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineGenAds;
})(typeof window !== 'undefined' ? window : globalThis);
