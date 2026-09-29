  /* ------------------------------------------------------------ [pinestream] stream */

  var STREAM_FPS = [[1, '1'], [2, '2'], [3, '3'], [5, '5']];
  var STREAM_WIDTH = [[480, '480'], [640, '640'], [800, '800']];
  var STREAM_QUALITY = [[45, 'Low'], [60, 'Medium'], [75, 'High']];

  function buildStream(p) {
    var b = p.body;
    var live = make('div', 'pl-stream-live');
    live.setAttribute('role', 'status');
    live.appendChild(iconNode('c:circle--filled'));
    live.appendChild(make('b', '', 'LIVE to listeners'));
    var liveWords = make('span', '', '');
    live.appendChild(liveWords);
    live.hidden = true;
    b.appendChild(live);

    var sw = toggle('Stream to listeners', 'A small picture-in-picture on the stream page, for tailnet and public links. Off: nothing is captured or served. Each listener can hide it on their own page.', function (next, node) {
      sw.set(next);                    /* one owner with the header's PineStream */
      flipStream(next, node);
    });
    b.appendChild(sw.root);

    var srcRow = make('div', 'pl-row');
    var srcText = make('div', 'pl-row-text');
    srcText.appendChild(make('b', '', 'Source'));
    var srcCap = make('small', '', '');
    srcText.appendChild(srcCap);
    srcRow.appendChild(srcText);
    var src = segmented(STREAM_SOURCES.map(function (o) { return {value: o.value, label: o.label, title: o.title}; }),
      function (v) { pickStreamSource(v); }, 'Which screen PineStream shows');
    srcRow.appendChild(src.root);
    b.appendChild(srcRow);

    function pickRow(label, caption, opts, key, aria) {
      var row = make('div', 'pl-row');
      var text = make('div', 'pl-row-text');
      text.appendChild(make('b', '', label));
      text.appendChild(make('small', '', caption));
      row.appendChild(text);
      var seg = segmented(opts.map(function (o) { return {value: o[0], label: o[1]}; }),
        function (v) { saveSetting(key, v); paint(); }, aria);
      row.appendChild(seg.root);
      b.appendChild(row);
      return seg;
    }
    var fps = pickRow('Frames a second', 'Pictures of a screen, not video: two is plenty. Car and Funnel listeners get one every two seconds or slower.',
      STREAM_FPS, 'stream_fps', 'PineStream frames a second');
    var width = pickRow('Width', 'Pixels across, as the screen sends them.', STREAM_WIDTH, 'stream_width', 'PineStream picture width');
    var quality = pickRow('Quality', 'JPEG quality: higher is sharper and heavier on a phone.', STREAM_QUALITY, 'stream_quality', 'PineStream picture quality');

    var grid = make('div', 'pl-facts');
    var facts = {picture: fact(grid, 'Listeners see'), frame: fact(grid, 'Last frame'),
      size: fact(grid, 'Picture'), watching: fact(grid, 'Watching')};
    b.appendChild(grid);

    var prev = make('figure', 'pl-preview pl-stream-prev');
    var img = make('img');
    img.alt = 'What listeners see in the PineStream window';
    prev.appendChild(img);
    var cap = make('figcaption', '', '');
    prev.appendChild(cap);
    prev.hidden = true;
    b.appendChild(prev);
    b.appendChild(make('p', 'pl-muted', 'While it streams, the streamed screen carries a red LIVE badge with a stop button. A key field on that screen veils the picture (listeners read "private screen") until it is gone.'));
    p.parts = {live: live, liveWords: liveWords, sw: sw, src: src, srcCap: srcCap, fps: fps, width: width,
      quality: quality, facts: facts, prev: prev, img: img, cap: cap};
    ui.streamPrev = img;
  }

  function streamPictureWords(ps, on) {
    if (!on) return 'nothing (switched off)';
    var name = streamSourceName(ps.source);
    var pic = String(ps.picture || 'waiting');
    if (pic === 'live') return name + ', live';
    if (pic === 'private') return 'a veil: private screen' + (ps.why ? ' (' + ps.why + ')' : '');
    return 'a veil: waiting for ' + name;
  }

  function paintStream(p) {
    var on = streamOn();
    var s = model.settings || {};
    var ps = streamBlock();
    var src = streamSource();
    p.parts.sw.set(on);
    p.parts.sw.sw.disabled = !model.state;
    p.parts.src.set(src);
    setText(p.parts.srcCap, src === 'pineapp'
      ? 'the Pine app\'s window on the desk (the app captures itself while it is open)'
      : 'the PineTab\'s screen (the tablet captures itself - no prompt)');
    p.parts.fps.set(Number(s.stream_fps || ps.fps || 2));
    p.parts.width.set(Number(s.stream_width || ps.width || 640));
    p.parts.quality.set(Number(s.stream_quality || ps.quality || 60));
    setHidden(p.parts.live, !on);
    var watching = num(ps.watching);
    setText(p.parts.liveWords, on ? ' · ' + streamSourceName(src) + (isFinite(watching) ? ' · ' + watching + ' watching' : '') : '');
    var f = p.parts.facts;
    setText(f.picture, streamPictureWords(ps, on));
    setText(f.frame, on && isFinite(num(ps.frame_age)) ? fmtAgo(ps.frame_age) + (ps.agent ? ' · ' + ps.agent : '') : '--');
    var sz = Array.isArray(ps.size) && ps.size[0] ? ps.size[0] + '×' + ps.size[1] + (ps.kb ? ' · ' + ps.kb + ' kB' : '') : '--';
    setText(f.size, on ? sz : '--');
    setText(f.watching, on && isFinite(watching) ? String(watching) : '--');
    var showPrev = on && !!ps.preview && ps.picture === 'live';
    vcrHidden(p.parts.prev, !showPrev);
    setText(p.parts.cap, showPrev ? 'What listeners see now (once a second while this panel is open)' : '');
    syncStreamPreview();
  }

  function summaryStream() {
    if (!model.state && !model.settings) return '';
    if (!streamOn()) return 'off';
    var s = model.settings || {};
    return (streamSource() === 'pineapp' ? 'Pine app' : 'PineTab') + ' · ' + (s.stream_fps || streamBlock().fps || 2) + ' fps · LIVE';
  }

  /* The preview is the JPEG the listeners get, asked for once a second
   * (signed, so the desk's file: page needs no header) - and only while the
   * PineStream panel is open in a visible popup and the stream is live. */
  function streamPreviewUrl() {
    var ps = streamBlock();
    return ui.visible && ui.open.stream && streamOn() && ps.preview && ps.picture === 'live' ? stationUrl(ps.preview) : '';
  }

  function syncStreamPreview() {
    var img = ui.streamPrev;
    if (!img) return;
    if (streamPreviewUrl()) {
      if (ui.streamPrevTimer) return;
      var tick = function () {
        ui.streamPrevTimer = 0;
        var url = streamPreviewUrl();
        if (!url) return;
        img.src = url + (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
        ui.streamPrevTimer = root.setTimeout(tick, 1000);
      };
      tick();
      return;
    }
    if (ui.streamPrevTimer) { root.clearTimeout(ui.streamPrevTimer); ui.streamPrevTimer = 0; }
    if (img.getAttribute('src') && !streamOn()) {
      /* the last frame stays through the collapse, then goes */
      root.setTimeout(function () { if (!streamPreviewUrl()) img.removeAttribute('src'); },
        root.PineVcr ? root.PineVcr.OUT_MS + 80 : 0);
    }
  }

