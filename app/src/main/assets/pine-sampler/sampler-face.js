/* THE SAMPLER'S FACE: a wallpaper, waveforms on the pads, three knobs and an
 * edit sheet.
 *
 * "Make sure the sampler page also has these controls and functionality. I
 *  need to be able to set a wallpaper for the background of the sampler
 *  screen based on images from the Pine Box Gallery. When editing a clip,
 *  allow me to specify the details of the clip similar to the image with the
 *  same style of pop up. I want the sampler to have the aesthetic I am
 *  showing in these images."
 *
 * The reference is a hardware-style phone sampler: a photograph behind
 * everything, pads drawn as translucent tiles with their own waveform, a row
 * of rotary knobs above the grid, and an edit panel that drops down over the
 * pads with the clip's waveform and its play mode.
 *
 * WHY THIS IS A SEPARATE FILE. sampler.js is already the largest view in the
 * app and it owns the INSTRUMENT - the engine, the banks, the gestures, the
 * bytes. This owns only the FACE, and it reaches the instrument through the
 * seams sampler.js publishes rather than through its internals. The one new
 * seam is `onPad`, which exists because a face that polled for the selection
 * would be a timer running all day to catch something that happens when a
 * finger moves.
 *
 * EVERY KNOB MOVES SOUND. Pan did not exist in either engine when this was
 * asked for; it was added to the C++ core, the JNI, Kotlin and the Web Audio
 * engine FIRST, and verified round-tripping on the tablet, precisely so that
 * none of these three is a control that does nothing. This project has
 * shipped two of those already and they are worse than an empty space.
 */
(function (root) {
  'use strict';

  var SKIN_KEY = 'pineSamplerSkin';

  function sampler() { return root.PineSampler || null; }
  /* THE ENGINE THE SAMPLER IS ACTUALLY USING, which on the tablet is the
   * NATIVE one. `pineSampler` first, exactly as sampler.js does it:
   * PineSamplerEngine is the Web Audio implementation and it is published
   * under its own name even when the native engine owns the pads, so
   * preferring it here meant asking an engine with no pads in it how long
   * pad 1 was. It answered zero, the waveform drew nothing and every knob
   * read its default - a face wired to the wrong instrument. */
  function engine() { return root.pineSampler || root.PineSamplerEngine || null; }

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function host() {
    return document.getElementById('sampler') || document.querySelector('.pb-sampler');
  }

  /* ===================================================== the wallpaper === */

  /* THE SAME PICTURE THE STATION IS SELLING, unless the operator picked one.
   *
   * WallpaperWatch already answers "what art is on the block" for the tablet's
   * home screen, and the answer is the same here: `selling_now` first, then
   * the newest render. The difference is that this one is a CHOICE - the
   * operator can pin a picture they like and it stays until they change it,
   * because a background that moves under your hands while you are playing is
   * a distraction, not a feature.
   */
  var skin = {url: '', name: '', pinned: false};

  function loadSkin() {
    try {
      var saved = JSON.parse(root.localStorage.getItem(SKIN_KEY) || 'null');
      if (saved && saved.url) skin = saved;
    } catch (err) { /* no preference is the normal case */ }
  }

  function saveSkin() {
    try { root.localStorage.setItem(SKIN_KEY, JSON.stringify(skin)); }
    catch (err) { /* a preference is not worth an exception */ }
  }

  function paintSkin() {
    var where = host();
    if (!where) return;
    if (skin.url) {
      where.style.backgroundImage = 'url("' + skin.url + '")';
      where.classList.add('pb-skinned');
    } else {
      where.style.removeProperty('background-image');
      where.classList.remove('pb-skinned');
    }
  }

  function api() { return root.pineDesktop || null; }

  function get(route) {
    var bridge = api();
    if (bridge && typeof bridge.get === 'function') {
      return Promise.resolve(bridge.get(route)).then(function (text) {
        return typeof text === 'string' ? JSON.parse(text) : text;
      });
    }
    return fetch(route, {credentials: 'same-origin'}).then(function (res) {
      if (!res.ok) throw new Error('the station said ' + res.status);
      return res.json();
    });
  }

  /* A page of gallery pictures, newest first. Videos are dropped: a wallpaper
   * cannot be one, and this route serves .mp4 alongside the stills. */
  function pictures(limit) {
    return get('/api/generations?limit=' + (limit || 60)).then(function (log) {
      var rows = (log && log.generations) || [];
      var out = [];
      for (var i = 0; i < rows.length; i += 1) {
        var files = (rows[i] && rows[i].files) || [];
        for (var f = 0; f < files.length; f += 1) {
          var name = String(files[f] || '');
          if (/\.(png|jpe?g|webp)$/i.test(name)) out.push(name);
        }
      }
      return out;
    });
  }

  function urlFor(name) {
    return '/api/generations/image/' + encodeURIComponent(name);
  }

  var picker = null;
  function closePicker() {
    if (picker) { picker.remove(); picker = null; }
  }

  function openPicker() {
    closePicker();
    picker = make('div', 'pb-skins');
    var head = make('div', 'pb-skins-head');
    head.appendChild(make('b', '', 'Background'));
    var shut = make('button', 'pb-skins-x', '×');
    shut.addEventListener('click', closePicker);
    head.appendChild(shut);
    picker.appendChild(head);

    var row = make('div', 'pb-skins-acts');
    var follow = make('button', 'pb-skins-act',
      'Follow the station · whatever is being sold');
    follow.addEventListener('click', function () {
      skin = {url: '', name: '', pinned: false};
      saveSkin();
      paintSkin();
      followStation();
      closePicker();
    });
    var none = make('button', 'pb-skins-act', 'No picture');
    none.addEventListener('click', function () {
      skin = {url: '', name: '', pinned: true};
      saveSkin();
      paintSkin();
      closePicker();
    });
    row.appendChild(follow);
    row.appendChild(none);
    picker.appendChild(row);

    var grid = make('div', 'pb-skins-grid');
    picker.appendChild(grid);
    document.body.appendChild(picker);
    if (root.PineDismiss) root.PineDismiss.watch(picker, closePicker, []);

    pictures(60).then(function (names) {
      if (!picker) return;
      if (!names.length) {
        grid.appendChild(make('p', 'pb-skins-none', 'The gallery has no pictures yet.'));
        return;
      }
      names.slice(0, 48).forEach(function (name) {
        var tile = make('button', 'pb-skins-tile');
        /* The THUMBNAIL, not the full render. The slideshow route resizes and
         * caches per width; the gallery route does not, and forty-eight
         * full-size PNGs is the 3.7 MB mistake all over again. */
        tile.style.backgroundImage =
          'url("/api/slideshow/media/' + encodeURIComponent(name) + '?w=320")';
        tile.title = name;
        tile.addEventListener('click', function () {
          skin = {url: urlFor(name), name: name, pinned: true};
          saveSkin();
          paintSkin();
          closePicker();
        });
        grid.appendChild(tile);
      });
    }, function (err) {
      if (picker) grid.appendChild(make('p', 'pb-skins-none',
        'The gallery would not answer: ' + ((err && err.message) || err)));
    });
  }

  /* When nothing is pinned, wear whatever the station is selling. */
  function followStation() {
    if (skin.pinned) return;
    var feed = root.PineStationFeed;
    var state = feed && feed.state ? (feed.state() || {}) : {};
    var sold = state.selling_now;
    var name = sold && sold.image ? String(sold.image) : '';
    if (name) {
      if (skin.name === name) return;
      skin = {url: urlFor(name), name: name, pinned: false};
      paintSkin();
      return;
    }
    if (skin.url) return;                 /* keep the last one rather than blank */
    pictures(12).then(function (names) {
      if (skin.pinned || !names.length) return;
      skin = {url: urlFor(names[0]), name: names[0], pinned: false};
      paintSkin();
    }, function () { /* no gallery, no background */ });
  }

  /* ================================================ waveforms on the pads == */

  /* WHY THE PADS CARRY A PICTURE OF THEIR SOUND. Sixteen tiles of text all
   * look the same at arm's length; sixteen waveforms do not. The engine
   * already computes peaks for the trim editor, so this is a read, not a
   * decode - and it is cached per pad because a bank repaint should not be
   * sixteen analyses. */
  var peakCache = Object.create(null);

  function peaksFor(key) {
    if (peakCache[key]) return peakCache[key];
    var audio = engine();
    if (!audio || typeof audio.peaks !== 'function') return null;
    var got = null;
    try { got = audio.peaks(key, 64); } catch (err) { got = null; }
    if (got && got.length) peakCache[key] = got;
    return got;
  }

  function forgetPeaks(key) { delete peakCache[key]; }

  function drawPadWave(cell, key) {
    var canvas = cell.querySelector('.pb-pad-wave');
    var bars = peaksFor(key);
    if (!bars) {
      if (canvas) canvas.remove();
      return;
    }
    if (!canvas) {
      canvas = make('canvas', 'pb-pad-wave');
      canvas.width = 128;
      canvas.height = 44;
      cell.insertBefore(canvas, cell.firstChild);
    }
    var pen = canvas.getContext('2d');
    pen.clearRect(0, 0, canvas.width, canvas.height);
    var mid = canvas.height / 2;
    var step = canvas.width / bars.length;
    pen.fillStyle = 'rgba(18, 26, 32, .78)';
    for (var i = 0; i < bars.length; i += 1) {
      var v = Math.max(0, Math.min(1, Number(bars[i]) || 0));
      var h = Math.max(1, v * mid);
      pen.fillRect(i * step, mid - h, Math.max(1, step - 0.6), h * 2);
    }
  }

  /* ============================== #1198: a video pad wears its own frame == */

  /* "If I put the video on a sampler pad, I want the video on the sampler
   *  pad so I see the thumbnail of it ... Have the video on the sampler pad
   *  faded to 30% or whatever I said it to in the preferences."
   *
   * THE SAME IDEA AS THE WAVEFORM ABOVE, CARRIED ONE STEP FURTHER. Sixteen
   * tiles of text look the same at arm's length; sixteen waveforms do not;
   * and a clip that HAS a picture is better recognised by its picture than
   * by a drawing of its soundtrack. So a video pad shows a still of itself
   * and an audio pad keeps its waveform, exactly as today.
   *
   * WHAT A PAD ALREADY KNEW, AND WHAT IT DID NOT. #1310 set two fields on
   * the pad's metadata at import time, off the RESPONSE'S OWN Content-Type
   * rather than a flag a caller has to remember to pass:
   *
   *     meta.video = true          it decoded from a video/* body
   *     meta.url   = <signed url>  the clip's own signed media url
   *
   * plus `meta.srcId`, the clip's id, which every import already carried.
   * That is the whole of what a still and a film need, so nothing had to be
   * added to the metadata and no pad had to be re-imported - a pad the
   * operator filled last week lights up with this the moment it repaints.
   *
   * THE STILL IS THE STATION'S, NOT OURS. GET /api/sfx/poster/{sid} renders
   * one frame per clip in a worker thread behind a semaphore of two, seeks
   * before the input for a keyframe, caches under data/sfx_posters/ and
   * prunes to six hundred. There is exactly one poster road on this station
   * and this is it; drawing a second thumbnail here - grabbing a frame off
   * the decoded pad into a canvas, say - would be a second answer to the
   * same question, and the two would disagree the first time the seek
   * changed.
   */

  /* WHERE THE STATION IS, FOR ANYTHING THAT PUTS A PATH IN AN <img src>.
   *
   * #1348: the desktop chrome is a file:// document, so a root-relative url
   * resolves to file:///api/... and loads nothing at all. The tablet's panel
   * IS served by the station, so there the relative url is the right one and
   * pineStationBase does not exist. Both, in four lines. */
  function mediaBase() {
    try {
      if (/^https?:$/.test(String(root.location.protocol))) return '';
      if (typeof root.pineStationBase === 'function') {
        return String(root.pineStationBase() || '').replace(/\/+$/, '');
      }
    } catch (err) { /* not a browser, or no shell */ }
    return '';
  }

  /* THE POSTER CALL, IN THE STATION'S ONE SPELLING.
   *
   * Copied from sfx-tv.js posterOf(): the same route, the same id, and the
   * signature LIFTED OFF THE CLIP'S OWN URL rather than asked for a second
   * time - it is the same media sign both routes check.
   *
   * ONE DELIBERATE DIFFERENCE, AND IT IS A CORRECTION. posterOf decides
   * video-or-not by looking for a file extension on the url. Measured
   * against this station: an sfx clip's url is `/sfx/<16 hex>?t=<sig>` and
   * has NO extension - app.py builds it that way in eight places - so that
   * test answers false for every clip in the cycle. A pad does not have to
   * guess: meta.video came from the Content-Type of the bytes it decoded,
   * which is the authoritative answer, so it is used here. An audio pad
   * asks for nothing at all and keeps its waveform.
   * (Reported rather than fixed at the source: sfx-tv.js belongs to another
   * hand tonight.) */
  function posterUrlFor(meta) {
    if (!meta || !meta.video) return '';
    var url = String(meta.url || '');
    var id = String(meta.srcId || '');
    /* The same fallback sfx-tv's clipId uses: older rows carry only the url. */
    if (!id) {
      var got = /\/sfx\/([^?#/]+)/.exec(url);
      id = got ? got[1] : '';
    }
    if (!id) return '';
    var m = /[?&]t=([^&#]+)/.exec(url);
    var sign = m ? m[1] : '';
    return mediaBase() + '/api/sfx/poster/' + encodeURIComponent(id)
      + (sign ? '?t=' + sign : '');
  }

  /* SIXTEEN PADS MUST NOT ALL ASK AT ONCE.
   *
   * The poster road renders behind a semaphore of two, so sixteen tiles
   * asking together is not sixteen requests, it is a queue fourteen deep
   * with an ffmpeg at the front of it - and a bank change while that queue
   * drains is another sixteen behind those. So this keeps at most two in
   * flight, the same two the station will serve, and everything else waits
   * its turn here where it can be thrown away.
   *
   * WHAT THE CACHE IS. One record per PAD KEY ("bank:pad"), holding the url
   * it was built for and the <img> element itself. The element is reused,
   * never rebuilt - an <img> that has loaded and is moved between parents
   * does not fetch again - so a pad is asked for exactly ONCE per session
   * however many times its bank is repainted. The url is kept beside it so
   * that a pad the operator refills with a different clip is spotted and
   * asked again rather than showing the old clip's frame.
   *
   * WHAT A BANK CHANGE DOES. Loaded posters are KEPT: coming back to bank 1
   * must not re-ask the station for pictures it has already handed over.
   * What is dropped is the QUEUE - any pad still waiting whose bank is no
   * longer the one on screen is taken out of the line, because the operator
   * has stopped looking at it, and its record is cleared so that it is
   * asked again cleanly if he comes back. Requests already in flight are
   * left to land; cancelling them would waste the ffmpeg the station has
   * already started. */
  var POSTER_AT_ONCE = 2;          /* the station's own semaphore is two */
  var posters = Object.create(null);   /* "bank:pad" -> record */
  var posterQueue = [];
  var posterLive = 0;

  function forgetPoster(key) {
    var rec = posters[key];
    if (rec) rec.dropped = true;
    delete posters[key];
  }

  /* Both pictures a pad can carry, forgotten together - used when a pad is
   * deleted or overwritten. */
  function forgetPad(key) {
    forgetPeaks(key);
    forgetPoster(key);
  }

  function posterPump() {
    while (posterLive < POSTER_AT_ONCE && posterQueue.length) {
      var rec = posterQueue.shift();
      if (!rec || rec.dropped || posters[rec.key] !== rec) continue;
      posterLive += 1;
      rec.state = 'flight';
      rec.img = make('img', 'pb-pad-shot');
      rec.img.alt = '';
      rec.img.addEventListener('load', posterLanded(rec, 'ok'));
      /* A 404 is the station's honest answer for a clip it cannot draw -
       * an older mp4 ffmpeg will not seek, or a pad whose video came from
       * some road the sfx shelf has never heard of. The pad falls back to
       * its waveform and nothing is said about it. */
      rec.img.addEventListener('error', posterLanded(rec, 'bad'));
      rec.img.src = rec.url;
    }
  }

  function posterLanded(rec, how) {
    return function () {
      if (rec.state !== 'flight') return;    /* load and error both fired */
      rec.state = how;
      posterLive = Math.max(0, posterLive - 1);
      posterPump();
      if (how === 'ok' && !rec.dropped) paintPadFaces();
    };
  }

  /* The record for this pad, asking the station for it if this is the first
   * time. Answers null for a pad that has no poster to have. */
  function posterFor(bank, pad, meta) {
    var url = posterUrlFor(meta);
    if (!url) return null;
    var key = bank + ':' + pad;
    var rec = posters[key];
    if (rec && rec.url === url) return rec;
    if (rec) rec.dropped = true;             /* the pad was refilled */
    rec = {key: key, bank: bank, pad: pad, url: url,
           state: 'queued', img: null, dropped: false};
    posters[key] = rec;
    posterQueue.push(rec);
    posterPump();
    return rec;
  }

  /* Everything still standing in line for a bank nobody is looking at. */
  function dropQueuedElsewhere(bank) {
    if (!posterQueue.length) return;
    var kept = [];
    for (var i = 0; i < posterQueue.length; i += 1) {
      var rec = posterQueue[i];
      if (rec.bank === bank) { kept.push(rec); continue; }
      rec.dropped = true;
      if (posters[rec.key] === rec) delete posters[rec.key];
    }
    posterQueue = kept;
  }

  /* HOW STRONGLY THE PICTURE SHOWS, 0..1 - his number, from his
   * preferences. The 0.3 here is the fallback for a face running in front
   * of an older sampler.js with no such seam, and it is the same 30 he
   * asked for, so a missing seam cannot make the pads go blank. */
  function padVideoFade() {
    var api_ = sampler();
    if (api_ && typeof api_.padVideoFade === 'function') {
      try {
        var got = Number(api_.padVideoFade());
        if (isFinite(got)) return Math.max(0, Math.min(1, got));
      } catch (err) { /* fall through to his default */ }
    }
    return 0.3;
  }

  function dropClass(cell, cls) {
    var node = cell.querySelector('.' + cls);
    if (node && node.parentNode) node.parentNode.removeChild(node);
  }

  /* TWO PICTURES ON ONE PAD IS ONE TOO MANY. While a pad is running its
   * film, its own still is taken out of sight rather than left underneath
   * it: at 30% you see THROUGH the moving frame to the frozen one, and a
   * clip playing over a stopped copy of itself is the ugliest thing this
   * pad could do. Hidden rather than removed, so letting go puts it back
   * with no round trip and no repaint of the rest of the bank. */
  function veilPoster(bank, pad, on) {
    var rec = posters[bank + ':' + pad];
    if (rec && rec.img) rec.img.style.visibility = on ? 'hidden' : '';
  }

  function filmIsOn(bank, pad) {
    return !!(film && film.bank === bank && film.pad === pad);
  }

  /* The still, under the label, at the fade he set. */
  function drawPadPoster(cell, rec, fade) {
    if (!rec || rec.state !== 'ok' || !rec.img) return false;
    if (rec.img.parentNode !== cell) cell.insertBefore(rec.img, cell.firstChild);
    rec.img.style.opacity = String(fade);
    /* Said on every repaint as well as at the two moments below, because a
     * frame that lands DURING a hold would otherwise arrive unveiled. */
    rec.img.style.visibility = filmIsOn(rec.bank, rec.pad) ? 'hidden' : '';
    return true;
  }

  function paintPadFaces() {
    var api_ = sampler();
    if (!api_) return;
    var bank = api_.bankIndex();
    var layout = api_.layout();
    dropQueuedElsewhere(bank);
    var fade = padVideoFade();
    for (var p = 0; p < api_.padCount; p += 1) {
      var cell = document.getElementById('pad-' + p);
      if (!cell) continue;
      var meta = layout[bank][p];
      if (!meta) {
        dropClass(cell, 'pb-pad-wave');
        dropClass(cell, 'pb-pad-shot');
        continue;
      }
      /* A VIDEO PAD SHOWS ITS FRAME, AN AUDIO PAD SHOWS ITS SOUND, AND A
       * VIDEO PAD WHOSE FRAME HAS NOT ARRIVED YET SHOWS ITS SOUND TOO.
       *
       * The poster is a round trip and an ffmpeg at the far end of it; a
       * tile that went blank while it waited would be a pad that looks
       * broken for as long as the queue is deep. The waveform is already
       * there and costs nothing, so it holds the tile until the frame
       * lands and is taken off the moment it does. */
      var rec = posterFor(bank, p, meta);
      if (drawPadPoster(cell, rec, fade)) {
        dropClass(cell, 'pb-pad-wave');
      } else {
        dropClass(cell, 'pb-pad-shot');
        drawPadWave(cell, api_.padKey(bank, p));
      }
    }
    /* A film already running follows the dial without waiting for the next
     * hold - see the note on the dial in sampler.js. */
    if (film && film.el) film.el.style.opacity = String(fade);
  }

  /* ========================== #1198: hold the pad and the video runs ===== */

  /* "whenever I tap and hold it I want the video to play until I let go of
   *  it on the sampler pad."
   *
   * ONE ELEMENT FOR THE WHOLE GRID, AND THAT IS THE CHOKE RULE.
   *
   * The sampler already has a name for "these two cannot both have the
   * floor": a choke group. sampler-engine.js cutSiblings() fades any voice
   * sharing the pressed pad's `choke`, and a choked voice does not come
   * back when the one that took the floor is released.
   *
   * EVERY VIDEO PAD IS IN ONE CHOKE GROUP, because there is one screen and
   * one pair of eyes. Hold pad 8 and it runs; put a second finger on pad 12
   * and 12 takes the picture - 8 keeps SOUNDING, its voice was never choked
   * and POLY still governs that, but it drops back to its poster. Lift 12
   * and the picture stops; it does not hand back to 8, exactly as a choked
   * voice does not come back. Lifting 8 after that does nothing at all,
   * because 8 is not the pad showing.
   *
   * The cost of the alternative is the argument for it: two 110-pixel films
   * at 30% behind two labels is not two things being watched, it is neither
   * being watched, on a tablet paying for two decoders to do it.
   */
  var film = null;     /* {key, bank, pad, el, src, from, to, loop, ceiling} */

  /* THE CEILING, AND WHY IT IS FLAT.
   *
   * sampler-air.js keeps one on the duck for the same reason and says it
   * best: a holder that forgets to let go leaves the station in a state
   * nobody can see the cause of. Every release path is wired below, but the
   * one that is missed is by definition the one nobody thought of, so the
   * film also dies of old age.
   *
   * IT IS NOT THE LENGTH OF THE CLIP. That was the first shape of this and
   * it is wrong twice over: a finger routinely outlasts a two-second sting,
   * so the ceiling would fire on a perfectly normal hold - snatching the
   * picture out from under a thumb that is still down - and it would log
   * "never released" about a release that was about to arrive, which is a
   * meter that cries wolf. A film paused on its last frame costs nothing;
   * the only thing this guards against is a release that never comes, and
   * two minutes is the right order of magnitude for that. It is also longer
   * than any clip on this shelf, so a pad set to LOOP can be held for as
   * long as anyone would want to hold one. */
  var FILM_CEILING_MS = 120000;

  /* ONE ELEMENT, KEPT FOR THE LIFE OF THE PAGE. It is the choke rule made
   * physical - there is only ever one film, so there is only ever one
   * decoder - and it is also why the listeners below are wired HERE and not
   * at each start: a fresh pair on every hold, on a reused element, is a
   * listener leak that grows for as long as the operator plays. */
  var filmEl = null;
  /* WHAT IS ALREADY LOADED INTO IT, as it was HANDED OVER. Reading it back
   * off the element is no good: assign a relative url and `.src` answers
   * with an absolute one, so a comparison against what we meant is always
   * unequal - and assigning a src a media element already holds starts the
   * fetch again from the top. The whole point of keeping the element is
   * that holding the same pad twice is instant. */
  var filmSrc = '';

  function filmElement() {
    if (filmEl) return filmEl;
    var node = make('video', 'pb-pad-film');
    /* MUTED, AND SAID THREE WAYS. The property is what the autoplay policy
     * reads, the attribute is what a reload reads, and defaultMuted is what
     * survives a src change - a film that asks for sound is refused
     * permission to start at all, and it would be the clip twice over
     * anyway: the engine is already playing its audio track in the mix. */
    node.muted = true;
    node.defaultMuted = true;
    node.setAttribute('muted', '');
    node.playsInline = true;
    node.setAttribute('playsinline', '');
    node.setAttribute('webkit-playsinline', '');
    node.preload = 'auto';
    node.controls = false;
    /* sampler-air.js taps every element that ever plays, so it can keep the
     * last two minutes of the broadcast - and it skips anything the sampler
     * previews, by this mark, so a grab never samples the thing you just
     * grabbed. A muted film makes no sound, but being inside the sampler is
     * the reason, not the silence. */
    try { node.dataset.pineSelf = '1'; } catch (err) { /* no dataset */ }
    node.addEventListener('loadedmetadata', function () {
      if (film && film.el === node) filmSeekStart(film);
    });
    /* The out point, honoured by hand because a media element has no such
     * thing. Cheap: timeupdate fires about four times a second. */
    node.addEventListener('timeupdate', function () {
      if (!film || film.el !== node || !(film.to > film.from)) return;
      if (node.currentTime < film.to) return;
      if (film.loop) filmSeekStart(film);
      else { try { node.pause(); } catch (err) { /* already stopped */ } }
    });
    filmEl = node;
    return node;
  }

  function filmSeekStart(state) {
    try { state.el.currentTime = state.from; } catch (err) { /* not ready */ }
  }

  function filmPlay(state) {
    try {
      var got = state.el.play();
      if (got && typeof got.catch === 'function') {
        got.catch(function () { /* a frame the browser would not start */ });
      }
    } catch (err) { /* the pad still sounds */ }
  }

  function filmArmCeiling(state) {
    if (state.ceiling) root.clearTimeout(state.ceiling);
    state.ceiling = root.setTimeout(function () {
      state.ceiling = 0;
      if (film !== state) return;
      if (root.console) {
        root.console.warn('sampler: pad ' + (state.pad + 1)
          + ' held its picture for ' + Math.round(FILM_CEILING_MS / 1000)
          + 's and was never released - stopping it');
      }
      filmStopAll();
    }, FILM_CEILING_MS);
  }

  /* THE PAD'S OWN IN AND OUT, so the picture agrees with the sound.
   *
   * The trim is the engine's - the one the edit sheet writes and the one
   * fire() plays - so a pad trimmed to its second half shows its second
   * half. #1310 hands the same trim to the set for the same reason: one
   * editor, both halves of the clip. */
  function filmWindow(meta) {
    var from = 0;
    var to = 0;
    if (meta && meta.trim) {
      from = Math.max(0, Number(meta.trim.start) || 0);
      var end = Number(meta.trim.end) || 0;
      if (end > from) to = end;
    }
    return {from: from, to: to};
  }

  function filmStart(bank, pad, meta) {
    if (!meta || !meta.video || !meta.url) return false;
    var cell = document.getElementById('pad-' + pad);
    if (!cell) return false;
    var key = bank + ':' + pad;
    var win = filmWindow(meta);
    var src = mediaBase() + String(meta.url);

    /* The same pad hit again - a retrigger, or NOTE RPT - rewinds rather
     * than rebuilding, which is what the engine does with the same voice
     * and is the difference between a film and a stutter. */
    if (film && film.key === key && film.src === src && film.el) {
      film.from = win.from;
      film.to = win.to;
      filmSeekStart(film);
      filmPlay(film);
      filmArmCeiling(film);
      return true;
    }

    var node = filmElement();
    filmStopAll();                                        /* the choke */
    film = {key: key, bank: bank, pad: pad, el: node, src: src,
            from: win.from, to: win.to, loop: !!meta.loop, ceiling: 0};
    /* LOOP FOLLOWS THE PAD'S OWN PLAY MODE rather than being invented here.
     * A pad set to LOOP sounds until it is let go, so its picture should
     * too; a ONE SHOT's picture ending with its sound is the truth, and a
     * looping picture over a finished sound would be the pad claiming to
     * still be playing. */
    node.loop = film.loop;
    node.style.opacity = String(padVideoFade());
    if (filmSrc !== src) { filmSrc = src; node.src = src; }
    veilPoster(bank, pad, true);
    cell.insertBefore(node, cell.firstChild);
    filmSeekStart(film);
    filmPlay(film);
    filmArmCeiling(film);
    return true;
  }

  /* STOP THIS PAD'S FILM - and only if it is the one showing. A release for
   * a pad that was choked by a later hold must not take the later hold's
   * picture down with it, which is the whole of the two-fingers rule. */
  function filmStop(bank, pad) {
    if (!film) return false;
    if (film.bank !== bank || film.pad !== pad) return false;
    filmStopAll();
    return true;
  }

  function filmStopAll() {
    var state = film;
    film = null;
    if (!state) return;
    veilPoster(state.bank, state.pad, false);    /* the still comes back */
    if (state.ceiling) root.clearTimeout(state.ceiling);
    var node = state.el;
    if (!node) return;
    /* PAUSED, NOT STRIPPED. The src is left on the element so that holding
     * the same pad again is instant rather than a second fetch; the element
     * itself is taken out of the cell so the pad's still shows through
     * again underneath, which is what "let go of it" should look like. */
    try { node.pause(); } catch (err) { /* never started */ }
    if (node.parentNode) node.parentNode.removeChild(node);
  }

  /* Which pad is showing a film, for a caller that wants to know - and for
   * the test, which otherwise has to read a private. */
  function filmAt() {
    return film ? {bank: film.bank, pad: film.pad} : null;
  }

  /* ---- what the poster queue is doing, as numbers -----------------------
   *
   * Three plain reads, published rather than left private, because the
   * thing that has to be PROVED about this queue is a negative - that
   * sixteen pads do NOT go at the station together - and a negative proved
   * by reading a module's insides is a test that passes when the insides
   * are renamed. They are also the honest answer to "is it still asking",
   * which is a question the operator's console can put. */
  function posterNode(bank, pad) {
    var rec = posters[bank + ':' + pad];
    return rec ? rec.img : null;
  }
  function postersInFlight() { return posterLive; }
  function postersWaiting() { return posterQueue.length; }

  /* ====================================================== the knob row ==== */

  /* A ROTARY, DRIVEN VERTICALLY.
   *
   * Turning a knob by following the angle of the finger is how hardware
   * works and is miserable on glass: the pointer crosses the centre and the
   * value jumps half a turn. Every software sampler worth using drags
   * UP and DOWN instead, and that is what this does - a full travel is about
   * two hundred pixels, and holding shift is not available on a tablet so
   * fine adjustment comes from a slow drag rather than a modifier.
   */
  function knob(name, spec) {
    var wrap = make('div', 'pb-knob');
    wrap.dataset.knob = spec.key;
    var dial = make('div', 'pb-knob-dial');
    var mark = make('i', 'pb-knob-mark');
    dial.appendChild(mark);
    var label = make('span', 'pb-knob-name', name);
    var said = make('b', 'pb-knob-said', '');
    wrap.appendChild(dial);
    wrap.appendChild(label);
    wrap.appendChild(said);

    var dragging = false;
    var startY = 0;
    var startValue = 0;

    var show = function (value) {
      var unit = (value - spec.min) / (spec.max - spec.min);
      /* 270 degrees of travel, the hardware convention: seven o'clock round
       * to five o'clock, with the dead zone at the bottom. */
      mark.style.transform = 'rotate(' + (-135 + unit * 270).toFixed(1) + 'deg)';
      said.textContent = spec.say(value);
    };

    wrap.addEventListener('pointerdown', function (event) {
      var value = spec.read();
      if (value === null) return;
      dragging = true;
      startY = event.clientY;
      startValue = value;
      try { wrap.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
      wrap.classList.add('turning');
      event.preventDefault();
    });
    wrap.addEventListener('pointermove', function (event) {
      if (!dragging) return;
      var travel = (startY - event.clientY) / 200;
      var want = startValue + travel * (spec.max - spec.min);
      want = Math.max(spec.min, Math.min(spec.max, want));
      spec.write(want);
      show(want);
    });
    var stop = function () {
      if (!dragging) return;
      dragging = false;
      wrap.classList.remove('turning');
      spec.done();
    };
    wrap.addEventListener('pointerup', stop);
    wrap.addEventListener('pointercancel', stop);
    /* A double tap puts it back where it started - the only way to find
     * centre again on a control with no numbers under the thumb. */
    wrap.addEventListener('dblclick', function () {
      spec.write(spec.home);
      show(spec.home);
      spec.done();
    });

    wrap.show = show;
    wrap.spec = spec;
    return wrap;
  }

  var knobs = [];
  var faceRow = null;

  function selectedKey() {
    var api_ = sampler();
    if (!api_) return null;
    var bank = api_.bankIndex();
    var pad = api_.selectedPad();
    if (!api_.layout()[bank][pad]) return null;
    return {key: api_.padKey(bank, pad), bank: bank, pad: pad};
  }

  function padSetting(field, fallback) {
    var at = selectedKey();
    if (!at) return null;
    var audio = engine();
    var state = null;
    try { state = audio.get(at.key); } catch (err) { state = null; }
    if (state && field in state) return Number(state[field]);
    var meta = sampler().layout()[at.bank][at.pad];
    var got = meta ? Number(meta[field]) : NaN;
    return isFinite(got) ? got : fallback;
  }

  function setPadSetting(field, value) {
    var at = selectedKey();
    if (!at) return;
    var patch = {};
    patch[field] = value;
    try { engine().set(at.key, patch); } catch (err) { /* engine said no */ }
    var meta = sampler().layout()[at.bank][at.pad];
    if (meta) meta[field] = value;
  }

  function settled() {
    var api_ = sampler();
    if (api_) api_.save();
  }

  function buildFace() {
    var where = host();
    if (!where || faceRow) return;
    /* The grid lives inside .pb-right, not directly under the host, so the
     * row is inserted into the GRID'S OWN parent. `where.insertBefore(row,
     * grid)` throws NotFoundError when grid is a grandchild - which is
     * exactly what it did, silently taking the whole face with it. */
    var grid = where.querySelector('.pb-padwrap');
    if (!grid || !grid.parentNode) return;

    faceRow = make('div', 'pb-face');

    knobs = [
      knob('VOL', {
        key: 'gain', min: 0, max: 2, home: 1,
        say: function (v) { return Math.round(v * 100) + '%'; },
        read: function () { return padSetting('gain', 1); },
        write: function (v) { setPadSetting('gain', v); },
        done: settled
      }),
      knob('PITCH', {
        /* In SEMITONES on the face and a ratio underneath, because "+3" is a
         * thing a person can aim at and 1.1892 is not. */
        key: 'pitch', min: -24, max: 24, home: 0,
        say: function (v) {
          var n = Math.round(v);
          return n === 0 ? '0' : (n > 0 ? '+' : '') + n;
        },
        read: function () {
          var ratio = padSetting('pitch', 1);
          return ratio === null ? null : 12 * Math.log2(Math.max(0.03125, ratio));
        },
        write: function (v) { setPadSetting('pitch', Math.pow(2, Math.round(v) / 12)); },
        done: settled
      }),
      knob('PAN', {
        key: 'pan', min: -1, max: 1, home: 0,
        say: function (v) {
          var n = Math.round(v * 50);
          if (!n) return 'C';
          return (n < 0 ? 'L' : 'R') + Math.abs(n);
        },
        read: function () { return padSetting('pan', 0); },
        write: function (v) { setPadSetting('pan', v); },
        done: settled
      })
    ];
    knobs.forEach(function (k) { faceRow.appendChild(k); });

    var side = make('div', 'pb-face-acts');
    var edit = make('button', 'pb-face-act', 'EDIT');
    edit.addEventListener('click', function () { openEdit(); });
    var kill = make('button', 'pb-face-act', 'DELETE');
    kill.addEventListener('click', function () { deleteSelected(); });
    var skinBtn = make('button', 'pb-face-act pb-face-skin', 'BACKDROP');
    skinBtn.title = 'A picture from the Pine Box gallery behind the pads';
    skinBtn.addEventListener('click', openPicker);
    side.appendChild(edit);
    side.appendChild(kill);
    side.appendChild(skinBtn);
    faceRow.appendChild(side);

    grid.parentNode.insertBefore(faceRow, grid);
    paintFace();
  }

  function paintFace() {
    var at = selectedKey();
    if (faceRow) faceRow.classList.toggle('empty', !at);
    for (var i = 0; i < knobs.length; i += 1) {
      var value = knobs[i].spec.read();
      knobs[i].show(value === null ? knobs[i].spec.home : value);
    }
  }

  async function deleteSelected() {
    var api_ = sampler();
    var at = selectedKey();
    if (!api_ || !at) return;
    var meta = api_.layout()[at.bank][at.pad];
    var said = (meta && meta.label ? meta.label : 'this pad').slice(0, 48);
    if (!root.confirm('Delete pad ' + (at.pad + 1) + '?\n\n' + said)) return;
    /* Silence first, then remove - clearing under a sounding voice leaves a
     * sound with nothing left to stop it. */
    try { engine().stopAll(); } catch (err) { /* nothing playing */ }
    if (root.PineAir) root.PineAir.release('pad');
    /* #1198: and the picture with it. `at.key` is "bank:pad", which is the
     * poster cache's key too, so a pad deleted and refilled with a
     * different clip cannot come back wearing the old one's frame. */
    filmStop(at.bank, at.pad);
    forgetPad(at.key);
    await api_.forget(at.bank, at.pad);
    closeEdit();
    paintFace();
  }

  /* ======================================================== the edit sheet = */

  var sheet = null;
  var unwatchSheet = null;

  function closeEdit() {
    if (unwatchSheet) { unwatchSheet(); unwatchSheet = null; }
    if (sheet) { sheet.remove(); sheet = null; }
  }

  function openEdit(which) {
    var api_ = sampler();
    if (!api_) return;
    if (which !== undefined) api_.select(which);
    var at = selectedKey();
    closeEdit();
    if (!at) return;

    sheet = make('div', 'pb-edit');

    var stage = make('div', 'pb-edit-stage');
    var canvas = make('canvas', 'pb-edit-wave');
    canvas.id = 'pbEditWave';
    stage.appendChild(canvas);
    var lane = make('div', 'pb-edit-lane');
    lane.appendChild(make('i', 'pb-edit-band'));
    lane.appendChild(make('i', 'pb-edit-handle a'));
    lane.appendChild(make('i', 'pb-edit-handle b'));
    stage.appendChild(lane);
    sheet.appendChild(stage);

    var tabs = make('div', 'pb-edit-tabs');
    tabs.appendChild(make('span', 'pb-edit-tab on', 'SAMPLE'));
    sheet.appendChild(tabs);

    var row = make('div', 'pb-edit-row');
    var prev = make('button', 'pb-edit-arrow', '◀');
    prev.title = 'The pad before this one';
    prev.addEventListener('click', function () {
      openEdit((at.pad + api_.padCount - 1) % api_.padCount);
    });
    var next = make('button', 'pb-edit-arrow', '▶');
    next.title = 'The pad after this one';
    next.addEventListener('click', function () {
      openEdit((at.pad + 1) % api_.padCount);
    });

    var modes = make('div', 'pb-edit-modes');
    var mode = function (name, field, on) {
      var button = make('button', 'pb-edit-mode' + (on ? ' on' : ''), name);
      button.addEventListener('click', function () {
        if (field === 'oneshot') {
          /* ONE SHOT is the ABSENCE of loop, not a flag of its own - the
           * engine has one truth and the face must not invent a second. */
          setPadSetting('loop', false);
        } else {
          setPadSetting(field, !readMode(field));
        }
        settled();
        openEdit(at.pad);
      });
      return button;
    };
    modes.appendChild(mode('ONE SHOT', 'oneshot', !readMode('loop')));
    modes.appendChild(mode('REVERSE', 'reverse', readMode('reverse')));
    modes.appendChild(mode('LOOP', 'loop', readMode('loop')));

    row.appendChild(prev);
    row.appendChild(modes);
    row.appendChild(next);
    sheet.appendChild(row);

    var says = make('p', 'pb-edit-said', '');
    says.id = 'pbEditSaid';
    sheet.appendChild(says);

    var where = host();
    where.appendChild(sheet);
    if (root.PineDismiss) unwatchSheet = root.PineDismiss.watch(sheet, closeEdit, []);

    drawEdit(at);
    wireTrim(lane, at);
  }

  function readMode(field) {
    var at = selectedKey();
    if (!at) return false;
    var state = null;
    try { state = engine().get(at.key); } catch (err) { state = null; }
    if (state && field in state) return !!state[field];
    var meta = sampler().layout()[at.bank][at.pad];
    return !!(meta && meta[field]);
  }

  function padWindow(at) {
    var audio = engine();
    var total = 0;
    try { total = Number(audio.seconds(at.key)) || 0; } catch (err) { total = 0; }
    var state = null;
    try { state = audio.get(at.key); } catch (err) { state = null; }
    var trim = state && state.trim ? state.trim : null;
    var from = trim ? Math.max(0, Number(trim.start) || 0) : 0;
    var to = trim && Number(trim.end) > from
      ? Math.min(total, Number(trim.end)) : total;
    return {total: total, from: from, to: to};
  }

  function drawEdit(at) {
    var canvas = document.getElementById('pbEditWave');
    if (!canvas) return;
    var width = canvas.clientWidth || 560;
    var height = canvas.clientHeight || 150;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    var pen = canvas.getContext('2d');
    pen.clearRect(0, 0, width, height);

    var bars = null;
    try { bars = engine().peaks(at.key, Math.min(512, Math.max(64, width))); }
    catch (err) { bars = null; }
    if (bars && bars.length) {
      var mid = height / 2;
      var step = width / bars.length;
      pen.fillStyle = '#7fd4ea';
      for (var i = 0; i < bars.length; i += 1) {
        var v = Math.max(0, Math.min(1, Number(bars[i]) || 0));
        var h = Math.max(1, v * (mid - 6));
        pen.fillRect(i * step, mid - h, Math.max(1, step - 0.5), h * 2);
      }
    }
    var win = padWindow(at);
    var said = document.getElementById('pbEditSaid');
    var meta = sampler().layout()[at.bank][at.pad];
    if (said) {
      said.textContent = 'pad ' + (at.pad + 1) + ' · '
        + (win.to - win.from).toFixed(2) + 's of ' + win.total.toFixed(2) + 's'
        + (meta && meta.label ? ' · ' + meta.label.slice(0, 60) : '');
    }
    placeTrim(win);
  }

  function placeTrim(win) {
    if (!sheet) return;
    var lane = sheet.querySelector('.pb-edit-lane');
    if (!lane || !win.total) return;
    var a = win.from / win.total;
    var b = win.to / win.total;
    lane.querySelector('.pb-edit-handle.a').style.left = (a * 100).toFixed(2) + '%';
    lane.querySelector('.pb-edit-handle.b').style.left = (b * 100).toFixed(2) + '%';
    var band = lane.querySelector('.pb-edit-band');
    band.style.left = (a * 100).toFixed(2) + '%';
    band.style.width = ((b - a) * 100).toFixed(2) + '%';
  }

  function wireTrim(lane, at) {
    var holding = null;
    var at01 = function (event) {
      var box = lane.getBoundingClientRect();
      return Math.max(0, Math.min(1,
        (event.clientX - box.left) / Math.max(1, box.width)));
    };
    lane.addEventListener('pointerdown', function (event) {
      var win = padWindow(at);
      if (!win.total) return;
      var where = at01(event);
      holding = Math.abs(where - win.from / win.total)
        <= Math.abs(where - win.to / win.total) ? 'a' : 'b';
      try { lane.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
      move(event);
    });
    var move = function (event) {
      if (!holding) return;
      var win = padWindow(at);
      if (!win.total) return;
      var where = at01(event) * win.total;
      var from = win.from;
      var to = win.to;
      if (holding === 'a') from = Math.min(where, to - 0.02);
      else to = Math.max(where, from + 0.02);
      setPadSetting('trim', {start: Math.max(0, from), end: Math.min(win.total, to)});
      drawEdit(at);
    };
    lane.addEventListener('pointermove', move);
    var stop = function () {
      if (!holding) return;
      holding = null;
      settled();
    };
    lane.addEventListener('pointerup', stop);
    lane.addEventListener('pointercancel', stop);
  }

  /* ============================================================= startup == */

  var started = false;
  function start() {
    if (started) return;
    started = true;
    /* Never let the face take the instrument down with it: the sampler has
     * to play whether or not it is wearing a photograph. */
    try { build(); } catch (err) {
      if (root.console) root.console.warn('sampler face: ' + (err && err.message));
    }
  }

  function build() {
    loadSkin();
    paintSkin();
    buildFace();
    followStation();
    var api_ = sampler();
    if (api_ && api_.onPad) {
      api_.onPad(function () {
        paintFace();
        paintPadFaces();
      });
    }
    /* The station's idea of what it is selling changes on its own clock, and
     * only matters when nothing is pinned. Once a minute is plenty; the
     * gallery is not a slideshow here. */
    setInterval(followStation, 60000);
  }

  var out = {
    start: start, openEdit: openEdit, closeEdit: closeEdit,
    openPicker: openPicker, paintFace: paintFace, paintPadFaces: paintPadFaces,
    forgetPeaks: forgetPeaks,
    /* #1198: both of a pad's pictures forgotten together, and the three
     * doors the instrument presses to start and stop a film. sampler.js
     * owns WHEN - press, lift, the bank, the window losing focus - and this
     * file owns the element, because the pad's face is what it is for. */
    forgetPad: forgetPad,
    filmStart: filmStart, filmStop: filmStop, filmStopAll: filmStopAll,
    filmAt: filmAt,
    padVideoFade: padVideoFade,
    posterUrlFor: posterUrlFor, posterNode: posterNode,
    postersInFlight: postersInFlight, postersWaiting: postersWaiting,
    skin: function () { return skin; }
  };
  root.PineSamplerFace = out;
  if (typeof module !== 'undefined' && module.exports) module.exports = out;
})(typeof window !== 'undefined' ? window : globalThis);
