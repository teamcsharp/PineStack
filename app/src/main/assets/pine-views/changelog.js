/* PineChangeLog - Git-backed task chronology from the global audit footer. */
(function (root) {
  'use strict';

  var PANEL_ID = 'pineChangeLog';
  var panel = null;
  var cursor = '';
  var loading = false;
  var pageState = {entries: [], total: 0, has_more: false};
  var threeLoad = null;
  var refreshTimer = 0;

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function icon(mark, label) {
    try { return typeof root.pineIcon === 'function' ? root.pineIcon(mark, label) || '' : ''; }
    catch (err) { return ''; }
  }

  function api(path) {
    try {
      if (root.pineDesktop && typeof root.pineDesktop.get === 'function') {
        return Promise.resolve(root.pineDesktop.get(path));
      }
    } catch (err) { /* fall through to the station origin */ }
    var headers = {};
    try {
      var key = root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || '';
      if (key) headers.Authorization = 'Bearer ' + key;
    } catch (err) { /* a public station can omit this */ }
    return root.fetch(path, {headers: headers, cache: 'no-store'}).then(function (response) {
      if (!response.ok) throw new Error('changelog ' + response.status);
      return response.json();
    });
  }

  function threeUrl() {
    if (root.pineThreeUrl) return root.pineThreeUrl();
    if (typeof location !== 'undefined' && /^https?:$/.test(location.protocol)) return '/vendor/three.min.js';
    return 'http://127.0.0.1:8096/vendor/three.min.js';
  }

  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = threeUrl();
      script.onload = function () { resolve(root.THREE); };
      script.onerror = function () { threeLoad = null; reject(new Error('three.js did not load')); };
      document.head.appendChild(script);
    });
    return threeLoad;
  }

  function isMajor(entry) {
    return !!(entry && (entry.major || Number(entry.file_count) > 3));
  }

  function elapsed(value) {
    if (value === null || value === undefined || value === '') return 'not recorded';
    var ms = Number(value);
    if (!isFinite(ms) || ms < 0) return 'not recorded';
    if (ms < 1000) return Math.round(ms) + ' ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + ' s';
    return Math.floor(ms / 60000) + ' m ' + Math.round((ms % 60000) / 1000) + ' s';
  }

  function value(value) {
    return value === null || value === undefined || value === '' ? 'not recorded' : String(value);
  }

  function metric(label, content, muted) {
    var block = make('div', 'cl-metric');
    block.appendChild(make('small', '', label));
    var shown = make('b', muted ? 'muted' : '', content);
    block.appendChild(shown);
    return block;
  }

  function detailLine(label, content, cls) {
    var row = make('div', 'cl-detail ' + (cls || ''));
    row.appendChild(make('small', '', label));
    row.appendChild(make('span', '', content));
    return row;
  }

  function seedOf(text) {
    var value = 2166136261;
    String(text || '').split('').forEach(function (char) {
      value ^= char.charCodeAt(0);
      value += (value << 1) + (value << 4) + (value << 7) + (value << 8) + (value << 24);
    });
    return value >>> 0;
  }

  function random(seed) {
    var state = seed || 1;
    return function () {
      state += 0x6d2b79f5;
      var item = state;
      item = Math.imul(item ^ item >>> 15, item | 1);
      item ^= item + Math.imul(item ^ item >>> 7, item | 61);
      return ((item ^ item >>> 14) >>> 0) / 4294967296;
    };
  }

  function stopFlow(host) {
    var flow = host && host.__pineChangeFlow;
    if (!flow) return;
    flow.stopped = true;
    if (flow.frame) root.cancelAnimationFrame(flow.frame);
    if (flow.resize) flow.resize.disconnect();
    try { flow.renderer.dispose(); } catch (err) { /* detached canvas */ }
    if (host.contains(flow.renderer.domElement)) host.removeChild(flow.renderer.domElement);
    host.__pineChangeFlow = null;
  }

  function flowLabels(host, files) {
    var labels = make('div', 'cl-flow-labels');
    files.slice(0, 18).forEach(function (file) {
      labels.appendChild(make('span', file.binary ? 'binary' : '', String(file.path || 'changed file')));
    });
    if (files.length > 18) labels.appendChild(make('span', 'muted', '+' + (files.length - 18) + ' files'));
    host.appendChild(labels);
  }

  function renderFlow(host, entry) {
    if (!host || host.__pineChangeFlow || !entry) return;
    host.replaceChildren();
    flowLabels(host, entry.files || []);
    three().then(function (THREE) {
      if (!host.isConnected || host.__pineChangeFlow) return;
      var renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
      renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2));
      renderer.domElement.className = 'cl-flow-canvas';
      host.insertBefore(renderer.domElement, host.firstChild);
      var scene = new THREE.Scene();
      var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 80);
      camera.position.set(0, 7.6, 12.5);
      camera.lookAt(0, 0, 0);
      scene.add(new THREE.AmbientLight(0xdbeaf0, 1.25));
      var grid = new THREE.GridHelper(17, 17, 0x2f5863, 0x1d3139);
      grid.position.y = -1.35;
      scene.add(grid);
      var hub = new THREE.Mesh(new THREE.BoxGeometry(1.55, .52, .42),
        new THREE.MeshBasicMaterial({color: 0x65c7da, transparent: true, opacity: .95}));
      hub.position.y = -.12;
      scene.add(hub);
      var files = (entry.files || []).slice(0, 30);
      var next = random(seedOf(entry.commit));
      var nodes = files.map(function (file, index) {
        var columns = Math.max(3, Math.ceil(Math.sqrt(files.length || 1)));
        var target = new THREE.Vector3((index % columns - (columns - 1) / 2) * 2.0,
          .12, (Math.floor(index / columns) - (Math.ceil(files.length / columns) - 1) / 2) * 1.7);
        var start = new THREE.Vector3((next() - .5) * 15, (next() - .5) * 3.2,
          (next() - .5) * 10);
        var changed = Number(file.added || 0) + Number(file.deleted || 0);
        var color = file.binary ? 0xe3be63 : Number(file.deleted || 0) > Number(file.added || 0)
          ? 0xd88a9c : changed > 0 ? 0x54d18b : 0x8fa0ad;
        var mesh = new THREE.Mesh(new THREE.BoxGeometry(.9, .4, .28),
          new THREE.MeshBasicMaterial({color: color, transparent: true, opacity: .9}));
        mesh.position.copy(start);
        scene.add(mesh);
        var geometry = new THREE.BufferGeometry().setFromPoints([hub.position.clone(), target]);
        var line = new THREE.Line(geometry, new THREE.LineBasicMaterial({color: color, transparent: true, opacity: .35}));
        scene.add(line);
        return {mesh: mesh, start: start, target: target, line: line, phase: next() * Math.PI * 2};
      });
      function resize() {
        var width = Math.max(240, host.clientWidth || 540);
        var height = Math.max(190, Math.min(320, Math.round(width * .43)));
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      }
      var flow = {renderer: renderer, stopped: false, frame: 0,
        resize: typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null};
      host.__pineChangeFlow = flow;
      if (flow.resize) flow.resize.observe(host);
      resize();
      var began = Date.now();
      function frame() {
        if (flow.stopped || !host.isConnected || !host.closest('details[open]')) { stopFlow(host); return; }
        var seconds = (Date.now() - began) / 1000;
        var settle = Math.min(1, seconds / 1.55);
        nodes.forEach(function (node, index) {
          node.mesh.position.lerpVectors(node.start, node.target, settle);
          node.mesh.position.y += Math.sin(seconds * 1.8 + node.phase) * .055;
          node.mesh.rotation.y = Math.sin(seconds + index) * .13;
        });
        hub.rotation.y = Math.sin(seconds * .7) * .08;
        renderer.render(scene, camera);
        flow.frame = root.requestAnimationFrame(frame);
      }
      frame();
    }, function () {
      host.replaceChildren(make('span', 'cl-flow-unavailable', 'The affected-file map could not start.'));
    });
  }

  function entryNode(entry) {
    var details = make('details', 'cl-entry');
    var summary = make('summary', 'cl-entry-summary');
    var tick = make('i', 'cl-tick');
    tick.innerHTML = icon('c:checkmark', 'Committed task') || '';
    summary.appendChild(tick);
    var heading = make('div', 'cl-entry-heading');
    heading.appendChild(make('time', '', value(entry.completed_label)));
    heading.appendChild(make('b', '', value(entry.task_name)));
    heading.appendChild(make('span', '', entry.file_count + ' file' + (Number(entry.file_count) === 1 ? '' : 's')
      + ' / ' + value(entry.short_commit)));
    summary.appendChild(heading);
    var state = make('span', 'cl-entry-state', isMajor(entry) ? 'major' : 'task');
    state.textContent = isMajor(entry) ? 'major' : 'git';
    summary.appendChild(state);
    details.appendChild(summary);
    var body = make('div', 'cl-entry-body');
    if (entry.prompt) body.appendChild(detailLine('Prompt', entry.prompt, 'cl-prompt'));
    else body.appendChild(detailLine('Prompt', 'Not retained by Git for this historical change.', 'cl-unrecorded'));
    body.appendChild(detailLine('Goal', value(entry.goal)));
    body.appendChild(detailLine('Result', value(entry.result)));
    var metrics = make('div', 'cl-metrics');
    var tokens = entry.tokens || {};
    metrics.appendChild(metric('Tokens in', value(tokens.input), tokens.input === null || tokens.input === undefined));
    metrics.appendChild(metric('Tokens out', value(tokens.output), tokens.output === null || tokens.output === undefined));
    metrics.appendChild(metric('Files edited', String(entry.file_count || 0)));
    metrics.appendChild(metric('Time to complete', elapsed(entry.elapsed_ms), entry.elapsed_ms === null || entry.elapsed_ms === undefined));
    body.appendChild(metrics);
    body.appendChild(detailLine('Git', value((entry.git || {}).subject) + ' / ' + value(entry.short_commit)));
    var files = make('details', 'cl-files');
    files.appendChild(make('summary', '', 'Files changed (' + (entry.file_count || 0) + ')'));
    var fileList = make('div', 'cl-file-list');
    (entry.files || []).forEach(function (file) {
      var line = make('div', file.binary ? 'binary' : '');
      line.appendChild(make('code', '', value(file.path)));
      line.appendChild(make('span', '', file.binary ? 'binary' : '+' + Number(file.added || 0) + ' / -' + Number(file.deleted || 0)));
      fileList.appendChild(line);
    });
    files.appendChild(fileList);
    body.appendChild(files);
    if (isMajor(entry)) {
      var flow = make('details', 'cl-flow');
      flow.appendChild(make('summary', '', 'Affected file flow'));
      var board = make('div', 'cl-flow-board');
      flow.appendChild(board);
      flow.addEventListener('toggle', function () {
        if (flow.open) renderFlow(board, entry); else stopFlow(board);
      });
      body.appendChild(flow);
    }
    details.appendChild(body);
    return details;
  }

  function render() {
    if (!panel) return;
    var body = panel.querySelector('.cl-body');
    var count = panel.querySelector('.cl-count');
    body.replaceChildren();
    if (count) count.textContent = pageState.total ? pageState.total + ' committed changes' : '';
    if (pageState.stale) body.appendChild(make('p', 'cl-refreshing', pageState.entries.length
      ? 'Showing the saved station history while Git refreshes.'
      : 'Building the station history from Git...'));
    if (!pageState.entries.length && !loading && !pageState.stale) {
      body.appendChild(make('p', 'cl-empty', 'No committed changes are available.'));
    }
    pageState.entries.forEach(function (entry) { body.appendChild(entryNode(entry)); });
    if (loading) body.appendChild(make('p', 'cl-loading', 'Reading the Git history...'));
    if (pageState.has_more && !loading) {
      var more = make('button', 'cl-more', 'Older commits');
      more.type = 'button';
      more.addEventListener('click', function () { load(cursor); });
      body.appendChild(more);
    }
  }

  function load(before) {
    if (loading) return Promise.resolve(null);
    loading = true;
    render();
    var path = '/api/changelog?limit=60' + (before ? '&before=' + encodeURIComponent(before) : '');
    return api(path).then(function (result) {
      var rows = (result && result.entries) || [];
      pageState.entries = before ? pageState.entries.concat(rows) : rows;
      pageState.total = Number(result && result.total) || pageState.entries.length;
      pageState.has_more = !!(result && result.has_more);
      pageState.stale = !!(result && result.stale);
      pageState.warming = !!(result && result.warming);
      cursor = String(result && result.next_before || '');
      loading = false;
      render();
      if (pageState.stale && !before && !refreshTimer) {
        refreshTimer = root.setTimeout(function () {
          refreshTimer = 0;
          if (panel && !panel.hidden) load('');
        }, 1800);
      }
      return result;
    }, function (error) {
      loading = false;
      pageState.has_more = false;
      if (panel) {
        var body = panel.querySelector('.cl-body');
        body.replaceChildren(make('p', 'cl-error', 'Changelog unavailable: ' + String(error && error.message || error)));
      }
      return null;
    });
  }

  function close() {
    if (!panel) return;
    panel.querySelectorAll('.cl-flow-board').forEach(stopFlow);
    if (refreshTimer) { root.clearTimeout(refreshTimer); refreshTimer = 0; }
    panel.hidden = true;
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no video wall */ }
  }

  function build() {
    if (panel) return panel;
    panel = make('aside', 'pine-changelog');
    panel.id = PANEL_ID;
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Pine Box changelog');
    panel.setAttribute('data-pine-drag', '');
    var header = make('header', 'cl-head');
    var title = make('div');
    title.appendChild(make('b', '', 'Pine Box changelog'));
    title.appendChild(make('span', 'cl-count'));
    header.appendChild(title);
    var closeButton = make('button', 'cl-close');
    closeButton.type = 'button';
    closeButton.title = 'Close changelog';
    closeButton.setAttribute('aria-label', 'Close changelog');
    closeButton.innerHTML = icon('c:close--filled', 'Close') || 'x';
    closeButton.addEventListener('click', close);
    header.appendChild(closeButton);
    panel.appendChild(header);
    panel.appendChild(make('div', 'cl-body'));
    document.body.appendChild(panel);
    if (root.PineDismiss) root.PineDismiss.watch(panel, close);
    return panel;
  }

  function open() {
    build();
    if (!panel.hidden) { close(); return; }
    panel.hidden = false;
    pageState = {entries: [], total: 0, has_more: false, stale: false, warming: false};
    cursor = '';
    load('');
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no video wall */ }
  }

  root.PineChangeLog = {open: open, close: close, isMajor: isMajor, elapsed: elapsed};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineChangeLog;
})(typeof window !== 'undefined' ? window : globalThis);
