/* The album behind any playing sleeve.
 *
 * This is a view over the station's music index, request line, research
 * cache and catalogue reader. It owns no parallel queue or metadata. A
 * track only moves when one of those canonical roads confirms it moved. */
(function (root) {
  'use strict';

  var back = null;
  var timers = [];
  var active = null;
  var visualFrame = 0;
  var searchTimer = 0;
  var searchSequence = 0;

  function api() {
    return root.pineDesktop || {
      get: function () { return Promise.reject(new Error('no station bridge')); },
      post: function () { return Promise.reject(new Error('no station bridge')); }
    };
  }

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function media(url) {
    if (!url) return '';
    if (typeof root.desktopMusicUrl === 'function') return root.desktopMusicUrl(url);
    return String(url);
  }

  function clock(seconds) {
    var n = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
  }

  function clearTimers() {
    while (timers.length) clearTimeout(timers.pop());
  }

  function close() {
    clearTimers();
    clearTimeout(searchTimer);
    searchSequence += 1;
    if (visualFrame) root.cancelAnimationFrame(visualFrame);
    visualFrame = 0;
    if (back) back.remove();
    back = null;
    active = null;
  }

  function say(node, text, bad) {
    node.textContent = String(text || '');
    node.classList.toggle('bad', !!bad);
  }

  function action(label, title, run) {
    var button = make('button', 'pa-action', label);
    button.type = 'button';
    button.title = title;
    button.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (button.disabled) return;
      button.disabled = true;
      var was = button.textContent;
      button.textContent = 'working…';
      Promise.resolve(run(button)).then(function () {
        if (button.isConnected) {
          button.textContent = was;
          button.disabled = false;
        }
      }, function (err) {
        if (button.isConnected) {
          button.textContent = String((err && err.message) || err).slice(0, 42);
          timers.push(setTimeout(function () {
            if (button.isConnected) {
              button.textContent = was;
              button.disabled = false;
            }
          }, 3000));
        }
      });
    });
    return button;
  }

  function query(track) {
    return [track.title, track.artist].filter(Boolean).join(' ');
  }

  function request(track, front, note) {
    return api().post('/api/dj/request', {q: query(track)}).then(function (got) {
      if (!front) {
        say(note, 'Scheduled ' + String((got && got.title) || track.title)
          + ' in the request line.');
        return got;
      }
      var id = String((got && got.id) || track.id || '');
      if (!id) throw new Error('the station queued it without returning its id');
      return api().post('/api/dj/queue/move', {id: id, to: 'front'}).then(function () {
        say(note, 'Moved ' + String(track.title || 'the track') + ' to the top of the queue.');
      });
    });
  }

  function jobWatch(job, note) {
    if (!back || !job) return;
    api().get('/api/music/artist/read/' + encodeURIComponent(job)).then(function (got) {
      if (!back) return;
      var stage = String((got && got.stage) || 'reading');
      var pct = Math.round(Number(got && got.progress || 0) * 100);
      say(note, stage + ' · ' + pct + '%'
        + (got && got.current ? ' · ' + got.current : ''), stage === 'error');
      if (stage !== 'done' && stage !== 'error') {
        timers.push(setTimeout(function () { jobWatch(job, note); }, 1200));
      }
    }, function (err) {
      say(note, 'Could not read the lyric job: ' + ((err && err.message) || err), true);
    });
  }

  function facts(track) {
    var wrap = make('div', 'pa-facts');
    var rows = [
      ['Title', track.title], ['Artist', track.artist], ['Album', track.album],
      ['Length', track.seconds ? clock(track.seconds) : ''], ['Library id', track.id]
    ];
    Object.keys(track.tags || {}).forEach(function (key) {
      rows.push([key, track.tags[key]]);
    });
    rows.forEach(function (row) {
      if (row[1] === undefined || row[1] === null || row[1] === '') return;
      var line = make('div', 'pa-fact');
      line.appendChild(make('b', '', row[0]));
      line.appendChild(make('span', '', String(row[1])));
      wrap.appendChild(line);
    });
    if (track.stats) {
      var pre = make('pre', 'pa-record', JSON.stringify(track.stats, null, 2));
      wrap.appendChild(pre);
    }
    return wrap;
  }

  function trackRow(track, player, albumNote, box) {
    var details = make('details', 'pa-track');
    var summary = document.createElement('summary');
    summary.appendChild(make('span', 'pa-track-no', String(track.track || '')));
    var words = make('span', 'pa-track-words');
    words.appendChild(make('b', '', String(track.title || track.id || 'track')));
    words.appendChild(make('i', '', [track.artist, track.seconds ? clock(track.seconds) : '']
      .filter(Boolean).join(' · ')));
    summary.appendChild(words);
    details.appendChild(summary);
    var body = make('div', 'pa-track-body');
    var note = make('p', 'pa-note', 'Open to read the station file for this track.');
    body.appendChild(note);
    var controls = make('div', 'pa-actions');
    controls.appendChild(action('Preview', 'Play this track in the album player', function () {
      player.src = media(track.url);
      player.dataset.track = String(track.id || '');
      player.dataset.followStation = '0';
      updateHero(box, track, box.__albumData || {});
      return player.play().then(function () { say(albumNote, 'Previewing ' + track.title + '.'); });
    }));
    controls.appendChild(action('Schedule / requeue', 'Put this track on the request line', function () {
      return request(track, false, note);
    }));
    controls.appendChild(action('Top of queue', 'Queue this track and move it next without cutting the current song', function () {
      return request(track, true, note);
    }));
    controls.appendChild(action('Research and analyse', 'Read or build the DJs’ research note for this track', function () {
      say(note, 'The DJs are researching this track…');
      return api().get('/api/music/notes/' + encodeURIComponent(track.id)).then(function (got) {
        var text = (got && got.notes);
        if (typeof text !== 'string') text = JSON.stringify(text || got || {}, null, 2);
        var old = body.querySelector('.pa-analysis');
        if (old) old.remove();
        body.appendChild(make('pre', 'pa-analysis', text || 'No research note was returned.'));
        say(note, 'The DJ research and song analysis are on file below.');
      });
    }));
    controls.appendChild(action('Transcribe lyrics', 'Run this one track through the canonical lyric reader', function () {
      say(note, 'Sending this track through transcription and analysis…');
      return api().post('/api/music/track/read', {id: track.id}).then(function (got) {
        jobWatch(got && got.job, note);
      });
    }));
    body.appendChild(controls);
    var loaded = false;
    details.addEventListener('toggle', function () {
      if (!details.open || loaded || !track.id) return;
      loaded = true;
      say(note, 'Reading the station file…');
      api().get('/api/music/track/' + encodeURIComponent(track.id)).then(function (got) {
        body.insertBefore(facts(got || track), controls);
        say(note, 'Everything currently on file for the DJs.');
      }, function (err) {
        say(note, 'The station file could not be read: ' + ((err && err.message) || err), true);
      });
    });
    details.appendChild(body);
    return details;
  }

  function valueFrom(tags, names) {
    var keys = Object.keys(tags || {});
    for (var i = 0; i < keys.length; i += 1) {
      if (names.indexOf(keys[i].toLowerCase()) >= 0 && tags[keys[i]]) return tags[keys[i]];
    }
    return '';
  }

  function detailLine(track, data) {
    var tags = track.tags || {};
    var bits = [];
    if (track.title) bits.push(track.title);
    if (track.seconds) bits.push(clock(track.seconds));
    var genre = valueFrom(tags, ['genre', 'style']);
    var year = valueFrom(tags, ['date', 'year', 'originaldate']);
    if (genre) bits.push(String(genre));
    if (year) bits.push(String(year));
    if (data && data.count) bits.push(String(data.count) + ' tracks on this album');
    if (data && data.seconds) bits.push(clock(data.seconds) + ' total');
    return bits.join('  |  ');
  }

  function updateHero(box, track, data) {
    if (!box || !track) return;
    box.__currentTrack = track;
    box.__albumData = data || box.__albumData || {};
    var album = String((data && data.album) || track.album || 'This album');
    var artist = String((data && data.artist) || track.artist || 'Unknown artist');
    box.querySelector('.pa-title').textContent = album;
    box.querySelector('.pa-artist').textContent = artist;
    box.querySelector('.pa-track-name').textContent = String(track.title || 'Unknown track');
    box.querySelector('.pa-album-detail').textContent = detailLine(track, data || {});
    var art = box.querySelector('.pa-art');
    var artUrl = track.art || '';
    if (artUrl) {
      art.src = media(artUrl);
      art.hidden = false;
    } else {
      art.removeAttribute('src');
      art.hidden = true;
    }
    if (box.__votes && box.__votes.paint) box.__votes.paint();
  }

  function readHeroDetails(box, track, data) {
    if (!track || !track.id) return;
    var serial = (box.__detailSerial || 0) + 1;
    box.__detailSerial = serial;
    api().get('/api/music/track/' + encodeURIComponent(track.id)).then(function (full) {
      if (!back || serial !== box.__detailSerial) return;
      updateHero(box, Object.assign({}, track, full || {}), data);
    }, function () { /* the album index still has enough to remain useful */ });
  }

  function paintAlbum(box, seed, data) {
    box.__albumData = data || {};
    var list = box.querySelector('.pa-list');
    list.replaceChildren();
    var tracks = (data && data.tracks) || [];
    var player = box.querySelector('.pa-player');
    var note = box.querySelector('.pa-top-note');
    if (!tracks.length) {
      list.appendChild(make('p', 'pa-note bad', 'No indexed tracks were returned for this album.'));
      return;
    }
    tracks.forEach(function (row) { list.appendChild(trackRow(row, player, note, box)); });
    var current = tracks.filter(function (row) {
      return String(row.id || '') === String(seed.id || '');
    })[0] || tracks[0];
    updateHero(box, current, data);
    readHeroDetails(box, current, data);
    if (current && current.url && String(player.dataset.track || '') !== String(current.id || '')) {
      player.src = media(current.url);
      player.dataset.track = String(current.id || '');
      player.dataset.followStation = String(current.id || '') === String(active && active.id || '') ? '1' : '0';
    }
  }

  function loadAlbum(box, seed) {
    var note = box.querySelector('.pa-top-note');
    say(note, 'Reading the album from the station...');
    var path = '/api/music/album?track_id=' + encodeURIComponent(seed.id || '')
      + (!seed.id && seed.album ? '&album=' + encodeURIComponent(seed.album) : '')
      + (!seed.id && seed.artist ? '&artist=' + encodeURIComponent(seed.artist) : '');
    return api().get(path).then(function (got) {
      if (!back || !box.isConnected) return;
      paintAlbum(box, seed, got || {});
      say(note, 'Tap any track to inspect, analyse, transcribe, schedule, or play it.');
    }, function (err) {
      if (back) say(note, 'The album could not be read: ' + ((err && err.message) || err), true);
    });
  }

  function searchButton(kind, title, subtitle, track, box, results) {
    var button = make('button', 'pa-search-hit');
    button.type = 'button';
    button.appendChild(make('i', 'pa-search-kind', kind));
    var words = make('span', 'pa-search-words');
    words.appendChild(make('b', '', title));
    words.appendChild(make('small', '', subtitle));
    button.appendChild(words);
    button.addEventListener('click', function () {
      results.hidden = true;
      loadAlbum(box, track);
    });
    return button;
  }

  function wireSearch(box) {
    var form = box.querySelector('.pa-search');
    var input = box.querySelector('.pa-search-input');
    var results = box.querySelector('.pa-search-results');

    function render(rows, query) {
      results.replaceChildren();
      if (!rows.length) {
        results.appendChild(make('p', 'pa-search-empty', 'Nothing in the local library matched "' + query + '".'));
        results.hidden = false;
        return;
      }
      var artists = Object.create(null);
      var albums = Object.create(null);
      rows.forEach(function (track) {
        var who = String(track.artist || 'Unknown artist');
        var album = String(track.album || 'Unknown album');
        if (!artists[who.toLowerCase()]) artists[who.toLowerCase()] = track;
        var key = who.toLowerCase() + '\n' + album.toLowerCase();
        if (!albums[key]) albums[key] = track;
      });
      Object.keys(artists).slice(0, 5).forEach(function (key) {
        var track = artists[key];
        results.appendChild(searchButton('artist', track.artist || 'Unknown artist',
          'Open ' + (track.album || 'a matching album'), track, box, results));
      });
      Object.keys(albums).slice(0, 12).forEach(function (key) {
        var track = albums[key];
        results.appendChild(searchButton('album', track.album || 'Unknown album',
          track.artist || 'Unknown artist', track, box, results));
      });
      rows.slice(0, 20).forEach(function (track) {
        results.appendChild(searchButton('track', track.title || track.id || 'Track',
          [track.artist, track.album].filter(Boolean).join(' | '), track, box, results));
      });
      results.hidden = false;
    }

    function search() {
      var query = String(input.value || '').trim();
      var mine = ++searchSequence;
      if (!query) { results.hidden = true; results.replaceChildren(); return; }
      results.hidden = false;
      results.replaceChildren(make('p', 'pa-search-empty', 'Searching the local music library...'));
      api().get('/api/music/search?q=' + encodeURIComponent(query) + '&limit=40').then(function (got) {
        if (!back || mine !== searchSequence) return;
        render((got && got.results) || [], query);
      }, function (err) {
        if (!back || mine !== searchSequence) return;
        results.replaceChildren(make('p', 'pa-search-empty',
          'The library search failed: ' + ((err && err.message) || err)));
      });
    }

    input.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(search, 180);
    });
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      clearTimeout(searchTimer);
      search();
    });
  }

  function startVisual(box, player) {
    var canvas = box.querySelector('.pa-visual');
    var remaining = box.querySelector('.pa-countdown strong');
    var position = box.querySelector('.pa-countdown small');
    var nodes = [];
    var lastFrame = 0;
    var lastSpawn = 0;

    function source() {
      if (!player.paused || player.dataset.followStation !== '1') return player;
      return document.getElementById('musicPlayer') || player;
    }

    function draw(now) {
      visualFrame = root.requestAnimationFrame(draw);
      if (!back || !canvas.isConnected || now - lastFrame < 34) return;
      var elapsed = Math.min(0.08, Math.max(0.016, (now - lastFrame) / 1000));
      lastFrame = now;
      var audio = source();
      var total = Number(audio && audio.duration) || Number(box.__currentTrack && box.__currentTrack.seconds) || 0;
      var at = Number(audio && audio.currentTime) || 0;
      remaining.textContent = clock(Math.max(0, total - at));
      position.textContent = clock(at) + ' / ' + clock(total) + '  remaining';

      var meters = root.PineMeters;
      var reading = null;
      if (meters && audio && audio.id) {
        meters.attach([audio.id]);
        reading = meters.read(audio.id, 'music');
      }
      var width = canvas.clientWidth || 1;
      var height = canvas.clientHeight || 1;
      var dpr = Math.min(2, root.devicePixelRatio || 1);
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      var context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.fillStyle = 'rgba(7, 13, 18, .30)';
      context.fillRect(0, 0, width, height);
      var bars = reading && reading.bars || [];
      if (bars.length && now - lastSpawn > 65) {
        lastSpawn = now;
        for (var i = 1; i < bars.length; i += 4) {
          var energy = Number(bars[i]) || 0;
          if (energy < 0.07 || Math.random() > 0.25 + energy * 0.65) continue;
          nodes.push({x: ((i + 0.5) / bars.length) * width, y: 0,
            speed: 22 + energy * 95, size: 1.2 + energy * 3.8,
            alpha: 0.3 + energy * 0.7});
        }
      }
      if (nodes.length > 180) nodes.splice(0, nodes.length - 180);
      for (var n = nodes.length - 1; n >= 0; n -= 1) {
        var dot = nodes[n];
        dot.y += dot.speed * elapsed;
        dot.alpha -= elapsed * 0.18;
        if (dot.y > height + 8 || dot.alpha <= 0) { nodes.splice(n, 1); continue; }
        context.beginPath();
        context.fillStyle = 'rgba(101, 199, 218, ' + Math.max(0, dot.alpha).toFixed(3) + ')';
        context.arc(dot.x, dot.y, dot.size, 0, Math.PI * 2);
        context.fill();
      }
    }

    var wake = function () {
      if (root.PineMeters) {
        root.PineMeters.wake();
        root.PineMeters.attach(['paPlayer', 'musicPlayer']);
      }
    };
    player.addEventListener('play', function () { player.dataset.followStation = '0'; wake(); });
    player.addEventListener('pointerdown', wake);
    visualFrame = root.requestAnimationFrame(draw);
  }

  function open(track) {
    var seed = track || {};
    if (!seed.id && !seed.album) return null;
    close();
    active = seed;
    back = make('div', 'pa-back');
    var box = make('section', 'pa-box');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Album and track desk');
    box.setAttribute('data-pine-drag', '');

    var search = make('form', 'pa-search');
    var searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.className = 'pa-search-input';
    searchInput.placeholder = 'Search artist, album, or song';
    searchInput.setAttribute('aria-label', searchInput.placeholder);
    var searchGo = make('button', 'pa-search-go');
    searchGo.type = 'submit'; searchGo.title = 'Search'; searchGo.setAttribute('aria-label', 'Search');
    searchGo.innerHTML = typeof root.pineIcon === 'function'
      ? (root.pineIcon('c:search', 'Search') || 'Search') : 'Search';
    search.appendChild(searchInput); search.appendChild(searchGo);
    box.appendChild(search);
    var searchResults = make('div', 'pa-search-results');
    searchResults.hidden = true;
    box.appendChild(searchResults);

    var head = make('header', 'pa-head');
    head.setAttribute('data-pine-drag-handle', '');
    var art = make('img', 'pa-art');
    art.alt = '';
    if (seed.art) art.src = media(seed.art);
    var names = make('div', 'pa-names');
    names.appendChild(make('b', 'pa-title', String(seed.album || 'Album')));
    names.appendChild(make('i', 'pa-artist', String(seed.artist || 'Unknown artist')));
    names.appendChild(make('strong', 'pa-track-name', String(seed.title || 'Unknown track')));
    names.appendChild(make('small', 'pa-album-detail', seed.seconds ? clock(seed.seconds) : ''));
    head.appendChild(art); head.appendChild(names);
    var countdown = make('div', 'pa-countdown');
    countdown.appendChild(make('span', '', 'TIME LEFT'));
    countdown.appendChild(make('strong', '', '0:00'));
    countdown.appendChild(make('small', '', '0:00 / 0:00'));
    head.appendChild(countdown);
    var votes = make('div', 'pa-votes');
    head.appendChild(votes);
    var shut = make('button', 'pa-close', 'x');
    shut.type = 'button'; shut.title = 'Close album'; shut.setAttribute('aria-label', 'Close album');
    shut.addEventListener('click', close);
    head.appendChild(shut);
    box.appendChild(head);

    var player = document.createElement('audio');
    player.id = 'paPlayer'; player.className = 'pa-player';
    player.controls = true; player.preload = 'metadata';
    player.setAttribute('data-pine-kind', 'music');
    box.appendChild(player);
    var visual = make('canvas', 'pa-visual');
    visual.setAttribute('aria-label', 'Live audio spectrum falling nodes');
    box.appendChild(visual);
    box.appendChild(make('p', 'pa-note pa-top-note', 'Reading the album from the station...'));
    box.appendChild(make('div', 'pa-list'));
    back.appendChild(box);
    back.addEventListener('click', function (event) { if (event.target === back) close(); });
    document.body.appendChild(back);

    box.__currentTrack = seed;
    if (root.PineVote) {
      box.__votes = root.PineVote.mount(votes, function () { return box.__currentTrack || seed; },
        function (words, bad) { say(box.querySelector('.pa-top-note'), words, bad); });
    }
    wireSearch(box);
    startVisual(box, player);
    loadAlbum(box, seed);
    return box;
  }

  root.addEventListener && root.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && back) close();
  });
  root.PineAlbum = {open: open, close: close, active: function () { return active; }};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineAlbum;
})(typeof window !== 'undefined' ? window : globalThis);
