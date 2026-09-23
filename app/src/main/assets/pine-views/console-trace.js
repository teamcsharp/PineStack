/* TAP THE CONSOLE LINE AND SEE WHERE THAT WORK CAME FROM.
 *
 * "I want to be able to tap on a console output entry and basically bring
 * up a pop-up allowing me to trace its entire path through the system
 * showing three JS simulations of where it started, where it's going, how
 * it came to be, and all of the related outputs that are connected to that
 * particular output that I'm analyzing."
 *
 * THE ANSWER IS ALREADY ON THE STATION, which is why this file is a view
 * and not an investigation. `GET /api/pipeline/detail?kind=&at=&find=`
 * (app.py:100590) was built for exactly this question and its docstring
 * reads like the request above:
 *
 *     "everything the station knows about one console line. The system
 *      prompt that armed it and the prompt as sent, every other time this
 *      happened, a per-minute chart of the last hour, what uses this road
 *      and where its output goes, the road written out step by step, and
 *      which step the work is standing on right now."
 *
 * So the tablet asks that one question and draws the answer. Building a
 * parallel tracer here would have meant a second, worse account of the
 * same events - and one that drifts the first time the station changes.
 *
 * WHAT IS DRAWN IN 3D, AND WHY THAT AND NOT MORE. The road, as a chain of
 * stations with the work standing on one of them. `road.flow` names the
 * steps in order, `stages[]` says which have been seen, when, and which is
 * `live`; `uses[]` are the roads that feed in and `goes` is where the
 * output leaves. That is a graph with a real topology and a real position
 * on it, so it is worth rendering as space. The prompts, the history and
 * the per-minute chart are text and numbers - they are shown as text and
 * numbers, because a bar chart made of cubes is harder to read than a bar
 * chart.
 *
 * THE CONSOLE LINE KEEPS A HISTORY. It showed only the newest row, so
 * "tap an entry" had exactly one entry to tap. It now holds the last rows
 * it has seen and the popup opens on whichever was tapped - the operator
 * is usually asking about the thing that just scrolled past, not the
 * thing on screen.
 */
(function (root) {
  'use strict';

  /* Resolved, not assumed: a leading slash is the station on the tablet and
   * the root of the DISK under file://. See pineThreeUrl in renderer.js. */
  function threeUrl() {
    if (window.pineThreeUrl) return window.pineThreeUrl();
    if (/^https?:$/.test(location.protocol)) return '/vendor/three.min.js';
    return 'http://127.0.0.1:8096/vendor/three.min.js';
  }
  var threeLoad = null;
  var box = null;          /* the popup */
  var scene = null;        /* the running simulation, if any */
  var openFor = null;      /* the row the popup is describing */
  var asking = false;

  /* THE STRIP AND THE PIPELINE SPEAK DIFFERENT VOCABULARIES.
   *
   * The console strip shows `note_activity` stages - there are eight of
   * them - and /api/pipeline/detail is keyed by PIPE_ROADS, of which
   * there are also eight, with different names. Asking for kind=voicing
   * returns a chart and nothing else, which is how the first build of
   * this popup opened: correct, empty, and useless.
   *
   * Each mapping below was read off the call site rather than guessed:
   *   writing    note_activity("writing")    -> the writing desk
   *   voicing    note_activity("voicing")    -> synthesis
   *   recasting  "legacy dialogue is being rebuilt between live turns"
   *   speaking   "Only now do we actually hand it to the box"
   *   sting      appended to the chat ring and aired
   *   held       "Pine Box switched off - kept for the page"
   *   mind       sets dj.speakbox_mind
   *   action     pipeline_log("action", ...) - its own kind, and it has
   *              no road, so the popup says so instead of drawing one.
   */
  var ROAD_OF = {
    writing: 'model',
    mind: 'speakbox',
    voicing: 'voice',
    recasting: 'voice',
    speaking: 'air',
    sting: 'air',
    held: 'air',
    action: 'action'
  };

  function roadFor(stage) {
    var key = String(stage || '').toLowerCase().trim();
    return ROAD_OF[key] || key;
  }

  function api() {
    return root.pineDesktop || {get: function () {
      return Promise.reject(new Error('no bridge'));
    }};
  }

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = threeUrl();
      tag.onload = function () { resolve(root.THREE); };
      tag.onerror = function () {
        threeLoad = null;
        reject(new Error('three.js did not load'));
      };
      document.head.appendChild(tag);
    });
    return threeLoad;
  }

  function ago(seconds) {
    var s = Number(seconds);
    if (!isFinite(s) || s < 0) return '';
    if (s < 60) return Math.round(s) + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    return (s / 3600).toFixed(1) + 'h ago';
  }

  /* ------------------------------------------------------- the popup */

  function close() {
    if (scene && scene.stop) { try { scene.stop(); } catch (e) { /* gone */ } }
    scene = null;
    openFor = null;
    if (box) box.hidden = true;
  }

  function build() {
    if (box) return box;
    box = make('div', 'ct-box');
    box.hidden = true;
    box.innerHTML =
      '<div class="ct-head">'
      + '<b class="ct-stage"></b>'
      + '<span class="ct-detail"></span>'
      + '<button class="ct-close" type="button" aria-label="close" title="close">×</button>'
      + '</div>'
      + '<div class="ct-road"><canvas class="ct-canvas"></canvas>'
      + '<div class="ct-roadwhy"></div></div>'
      + '<div class="ct-body"></div>';
    document.body.appendChild(box);

    box.querySelector('.ct-close').addEventListener('click', function (event) {
      event.stopPropagation();
      close();
    });
    /* Tap away closes it, like every other panel on this terminal. */
    if (root.PineDismiss) {
      root.PineDismiss.watch(box, close, [function () {
        return document.getElementById('pineConsoleLine');
      }]);
    }
    return box;
  }

  /* A section with a heading, added only when it has something in it -
   * an empty "Prompts" heading teaches the operator to stop looking. */
  function section(into, title, body) {
    if (!body) return;
    var wrap = make('div', 'ct-sec');
    wrap.appendChild(make('h4', '', title));
    wrap.appendChild(body);
    into.appendChild(wrap);
  }

  /* EVERY STEP OPENS.
   *
   * "Allow me to expand each of these to see what lines are being
   * referenced in these and see what the results are for each part of this
   * road and what contributed to making this happen."
   *
   * The station keeps that already and it is not in the summary. Every
   * pipeline row may carry an `extra` of up to 8000 characters -
   * pipeline_log's own words: "the actual prompt, the actual reply, the
   * actual lines mined" - and /api/pipeline/detail returns it for ONE row,
   * the one nearest the `at` it was given. Each stage carries its own `ts`,
   * so each stage can be asked for separately.
   *
   * Fetched on FIRST OPEN and then kept. Six stages fetched eagerly would
   * be six requests for a popup the operator may only glance at, against a
   * station with a documented history of being starved by chatty clients. */
  function stagesList(detail) {
    var rows = detail.stages || [];
    if (!rows.length) return null;
    var road = roadFor(openFor && openFor.stage);
    var list = make('ol', 'ct-stages');
    rows.forEach(function (st) {
      var li = make('li', 'ct-stage-row' + (st.live ? ' live' : '')
        + (st.seen ? '' : ' unseen'));

      if (!st.seen) {
        li.appendChild(make('b', '', String(st.label || '')));
        li.appendChild(make('i', 'ct-when', 'not reached'));
        list.appendChild(li);
        return;
      }

      var box = make('details', 'ct-step');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(st.label || '')));
      sum.appendChild(make('i', 'ct-when', ago(st.ago)));
      box.appendChild(sum);
      if (st.text) box.appendChild(make('p', 'ct-said', String(st.text)));

      var deeper = make('div', 'ct-deeper');
      box.appendChild(deeper);

      var asked = false;
      box.addEventListener('toggle', function () {
        if (!box.open || asked) return;
        asked = true;
        deeper.appendChild(make('p', 'ct-wait', 'asking what fed this step…'));
        var q = '/api/pipeline/detail?kind=' + encodeURIComponent(road)
          + (st.ts ? '&at=' + encodeURIComponent(String(st.ts)) : '');
        api().get(q).then(function (got) {
          deeper.replaceChildren();
          var event = (got && got.event) || {};
          var extra = String(event.extra || '').trim();
          var said = String(event.text || '').trim();
          if (said && said !== String(st.text || '').trim()) {
            deeper.appendChild(make('p', 'ct-said', said));
          }
          if (extra) {
            /* THE EVIDENCE, VERBATIM. This is the prompt as sent and the
             * lines it was shown; paraphrasing it would destroy the only
             * reason to open the step. */
            deeper.appendChild(make('h5', '', 'what went in, and what came back'));
            deeper.appendChild(make('pre', 'ct-pre', extra));
          }
          if (!extra && !said) {
            deeper.appendChild(make('p', 'ct-wait',
              'the station kept no detail for this step - it logged the '
              + 'event but not its workings.'));
          }
          /* What else happened on this road around the same moment: the
           * "related outputs" half of the question. */
          var near = (got && got.history) || [];
          if (near.length > 1) {
            var also = make('ul', 'ct-history');
            near.slice(0, 6).forEach(function (h) {
              var li2 = make('li', '');
              li2.appendChild(make('i', 'ct-when',
                h.ts ? new Date(Number(h.ts)).toLocaleTimeString() : ''));
              li2.appendChild(make('span', '', String(h.text || '')));
              also.appendChild(li2);
            });
            deeper.appendChild(make('h5', '', 'around it on this road'));
            deeper.appendChild(also);
          }
        }, function (err) {
          deeper.replaceChildren();
          deeper.appendChild(make('p', 'ct-wait',
            'could not read that step: ' + ((err && err.message) || err)));
        });
      });

      li.appendChild(box);
      list.appendChild(li);
    });
    return list;
  }

  function promptsList(detail) {
    var rows = detail.prompts || [];
    if (!rows.length) return null;
    var wrap = make('div', '');
    rows.slice(0, 4).forEach(function (p) {
      var d = make('details', 'ct-prompt');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(p.kind || 'a model call')));
      sum.appendChild(make('i', '', String(p.model || '')
        + (p.ms ? '  ·  ' + Math.round(Number(p.ms)) + ' ms' : '')
        + (p.num_ctx ? '  ·  ctx ' + p.num_ctx : '')
        + (p.armed ? '  ·  armed ' + p.armed : '')));
      d.appendChild(sum);
      if (p.prompt) {
        d.appendChild(make('h5', '', 'the prompt as sent'));
        d.appendChild(make('pre', 'ct-pre', String(p.prompt)));
      }
      if (p.text) {
        d.appendChild(make('h5', '', 'what came back'));
        d.appendChild(make('pre', 'ct-pre', String(p.text)));
      }
      wrap.appendChild(d);
    });
    return wrap;
  }

  function historyList(detail) {
    var rows = detail.history || [];
    if (!rows.length) return null;
    var list = make('ul', 'ct-history');
    rows.slice(-14).reverse().forEach(function (h) {
      var li = make('li', '');
      var when = h.ts ? new Date(Number(h.ts)).toLocaleTimeString() : '';
      li.appendChild(make('i', 'ct-when', when));
      li.appendChild(make('span', '', String(h.text || '')));
      list.appendChild(li);
    });
    return list;
  }

  /* The last hour, per minute, as a sparkline - drawn in the DOM because
   * sixty bars is sixty bars and does not need a renderer. */
  function chartOf(detail) {
    var rows = detail.chart || [];
    if (!rows.length) return null;
    var top = Math.max.apply(null, rows.concat([1]));
    var wrap = make('div', 'ct-chart');
    rows.forEach(function (v, i) {
      var bar = make('i', '');
      bar.style.height = Math.max(2, Math.round(100 * (Number(v) || 0) / top)) + '%';
      if (i === rows.length - 1) bar.className = 'now';
      bar.title = (Number(v) || 0) + ' in that minute';
      wrap.appendChild(bar);
    });
    return wrap;
  }

  /* ------------------------------------------- what the line used to be */

  /* THE FULL TRANSFORMATION, not just the finished line.
   *
   * "Show me what the original line was. I want to see the full
   * transformation of the original dialogue being fully transformed going
   * through the tinting process."
   *
   * /api/trail (app.py) keeps one record per tinted moment and its
   * docstring lists precisely the four things that answer this: "the plain
   * line, the rewritten line, the crystal passages it was shown and the
   * studio swath the plain line was built out of". It holds 600 of them
   * and is durable, where the pipeline loses its own copy after about four
   * minutes - so this is the right store to ask, not the ring.
   *
   * The trail has no line id in common with the console row, so the join
   * is by TEXT, and it is done honestly: a long shared run, not a fuzzy
   * score. A wrong match here would show the operator one line's origins
   * under another line's heading, which is worse than showing nothing. */
  var trail = null;
  var trailAt = 0;

  function trailRows() {
    if (trail && Date.now() - trailAt < 30000) return Promise.resolve(trail);
    return api().get('/api/trail?limit=60').then(function (got) {
      trail = (got && got.rows) || [];
      trailAt = Date.now();
      return trail;
    }, function () { return []; });
  }

  function boiled(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ')
      .replace(/[ ]+/g, ' ').trim();
  }

  /* A shared run of at least RUN characters. Long enough that a match is
   * the same sentence and not two lines that both say "the station". */
  var RUN = 34;
  function sameLine(a, b) {
    var x = boiled(a);
    var y = boiled(b);
    if (!x || !y || x.length < RUN || y.length < RUN) return false;
    if (x.indexOf(y) >= 0 || y.indexOf(x) >= 0) return true;
    for (var i = 0; i + RUN <= x.length; i += 6) {
      if (y.indexOf(x.substr(i, RUN)) >= 0) return true;
    }
    return false;
  }

  /* The text a console event is ABOUT. The voice road's extra is shaped
   * "INPUT to xtts (voice), #397:" then a newline then the line, so
   * the line is what follows it; other roads just carry the line. */
  function linesOf(detail) {
    /* EVERY TEXT THE TRACE ALREADY HOLDS, not just one.
     *
     * The first version read only `event.extra`, and measured against the
     * live station that field was EMPTY for the event it was handed - so
     * the match was attempted with an empty string and the popup reported
     * "not on the tint trail" about a line it had never actually looked
     * for. A false negative that reads exactly like a true one.
     *
     * The line can be in any of three places depending on which road the
     * console row came from, so all three are tried. */
    var out = [];
    var event = (detail && detail.event) || {};
    var extra = String(event.extra || '');
    if (extra) {
      var cut = extra.indexOf(String.fromCharCode(10));
      if (cut >= 0 && /INPUT to /i.test(extra.slice(0, cut))) {
        out.push(extra.slice(cut + 1).trim());
      } else {
        out.push(extra.trim());
      }
    }
    if (event.text) out.push(String(event.text).trim());
    (detail.stages || []).forEach(function (st) {
      if (st && st.text) out.push(String(st.text).trim());
    });
    (detail.history || []).slice(0, 6).forEach(function (h) {
      if (h && h.text) out.push(String(h.text).trim());
    });
    return out.filter(function (t) { return t && t.length >= RUN; });
  }

  function tintSection(detail) {
    var lines = linesOf(detail);
    if (!lines.length) return null;
    var wrap = make('div', 'ct-tint');
    wrap.appendChild(make('p', 'ct-wait', 'looking for this line on the trail…'));
    trailRows().then(function (rows) {
      var hit = null;
      for (var i = 0; i < rows.length && !hit; i += 1) {
        for (var k = 0; k < lines.length; k += 1) {
          if (sameLine(lines[k], rows[i].tinted)
            || sameLine(lines[k], rows[i].plain)) {
            hit = rows[i];
            break;
          }
        }
      }
      wrap.replaceChildren();
      if (!hit) {
        wrap.appendChild(make('p', 'ct-wait',
          'this line is not on the tint trail - it either went out as '
          + 'written, or it aired longer ago than the trail keeps.'));
        return;
      }
      var pair = make('div', 'ct-pair');
      var before = make('div', 'ct-before');
      before.appendChild(make('h5', '', 'as written'));
      before.appendChild(make('p', '', String(hit.plain || '(not recorded)')));
      var after = make('div', 'ct-after');
      after.appendChild(make('h5', '', 'as aired, after the tint'));
      after.appendChild(make('p', '', String(hit.tinted || '')));
      pair.appendChild(before);
      pair.appendChild(after);
      wrap.appendChild(pair);

      var facts = [];
      if (hit.road) facts.push(String(hit.road));
      if (hit.ms) facts.push(Math.round(Number(hit.ms) / 100) / 10 + 's in the lane');
      if (hit.liked) facts.push('marked good');
      if (facts.length) wrap.appendChild(make('i', 'ct-rate', facts.join('  ·  ')));

      /* WHAT IT WAS SHOWN. This is the "what contributed" half - the
       * crystal passages the rewrite was looking at while it worked. */
      var seen = hit.passages || [];
      if (seen.length) {
        wrap.appendChild(make('h5', '', 'the passages it was shown'));
        seen.slice(0, 5).forEach(function (pass) {
          var box = make('details', 'ct-prompt');
          var sum = make('summary', '');
          sum.appendChild(make('b', '', String(pass.crystal || 'a passage')));
          sum.appendChild(make('i', '', String(pass.file || '')));
          box.appendChild(sum);
          box.appendChild(make('pre', 'ct-pre', String(pass.text || '')));
          wrap.appendChild(box);
        });
      }
      var swath = hit.swath || {};
      if (swath.text) {
        wrap.appendChild(make('h5', '', 'the studio swath it was built from'));
        wrap.appendChild(make('pre', 'ct-pre', String(swath.text)));
      }
    });
    return wrap;
  }

  /* ------------------------------------------------- the road, in 3D */

  /* Stations along a line, the work standing on one of them, feeders
   * arriving from the left and the output leaving to the right. The
   * camera drifts rather than orbits: this is a diagram that happens to
   * have depth, and a diagram that spins is a diagram you cannot read. */
  function drawRoad(canvas, detail) {
    return three().then(function (THREE) {
      var stages = detail.stages || [];
      var road = detail.road || {};
      var uses = road.uses || [];
      if (!stages.length) return null;

      var renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true,
        alpha: true});
      renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2));
      var w = canvas.clientWidth || 320;
      var h = canvas.clientHeight || 150;
      renderer.setSize(w, h, false);

      var view = new THREE.Scene();
      var camera = new THREE.PerspectiveCamera(46, w / h, 0.1, 200);

      var span = Math.max(1, stages.length - 1);
      var step = 4.2;
      var left = -(span * step) / 2;

      var nodes = [];
      var liveAt = -1;
      stages.forEach(function (st, i) {
        var seen = !!st.seen;
        var live = !!st.live;
        if (live) liveAt = i;
        var geo = new THREE.SphereGeometry(live ? 0.85 : 0.58, 20, 16);
        var mat = new THREE.MeshBasicMaterial({
          color: live ? 0x65c7da : (seen ? 0x54d18b : 0x35414c),
          transparent: true,
          opacity: seen || live ? 0.95 : 0.4
        });
        var ball = new THREE.Mesh(geo, mat);
        ball.position.set(left + i * step, 0, 0);
        view.add(ball);
        nodes.push({mesh: ball, live: live, seen: seen, base: live ? 0.85 : 0.58});

        if (i > 0) {
          /* The rail between stations: bright where the work has been. */
          var from = new THREE.Vector3(left + (i - 1) * step, 0, 0);
          var to = new THREE.Vector3(left + i * step, 0, 0);
          var line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([from, to]),
            new THREE.LineBasicMaterial({
              color: seen ? 0x54d18b : 0x35414c,
              transparent: true, opacity: seen ? 0.7 : 0.25
            }));
          view.add(line);
        }
      });

      /* What feeds this road, arriving at the first station. */
      var feeders = [];
      uses.slice(0, 6).forEach(function (name, i) {
        var at = new THREE.Vector3(left - 3.4,
          ((i - (Math.min(uses.length, 6) - 1) / 2) * 1.5), -1.2);
        var dot = new THREE.Mesh(
          new THREE.SphereGeometry(0.26, 12, 10),
          new THREE.MeshBasicMaterial({color: 0xe3be63, transparent: true,
            opacity: 0.85}));
        dot.position.copy(at);
        view.add(dot);
        view.add(new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(
            [at, new THREE.Vector3(left, 0, 0)]),
          new THREE.LineBasicMaterial({color: 0xe3be63, transparent: true,
            opacity: 0.3})));
        feeders.push(dot);
      });

      /* And where the output leaves. */
      var out = new THREE.Mesh(
        new THREE.SphereGeometry(0.42, 14, 12),
        new THREE.MeshBasicMaterial({color: 0xd88ad0, transparent: true,
          opacity: 0.9}));
      out.position.set(left + span * step + 3.2, 0, 0);
      view.add(out);
      view.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(
          [new THREE.Vector3(left + span * step, 0, 0), out.position.clone()]),
        new THREE.LineBasicMaterial({color: 0xd88ad0, transparent: true,
          opacity: 0.35})));

      /* A packet running the length of the road it has covered, so the
       * direction of travel is visible without reading a single label. */
      var packet = new THREE.Mesh(
        new THREE.SphereGeometry(0.2, 10, 8),
        new THREE.MeshBasicMaterial({color: 0xffffff}));
      view.add(packet);

      var reach = liveAt >= 0 ? liveAt : stages.filter(function (s) {
        return s.seen;
      }).length - 1;
      if (reach < 0) reach = 0;

      camera.position.set(0, 2.6, Math.max(12, span * 2.6));
      camera.lookAt(0, 0, 0);

      var raf = 0;
      var t0 = performance.now();
      var alive = true;
      function frame() {
        if (!alive) return;
        raf = requestAnimationFrame(frame);
        var t = (performance.now() - t0) / 1000;

        /* The live station breathes. Nothing else moves, so the eye goes
         * straight to where the work actually is. */
        nodes.forEach(function (n) {
          if (!n.live) return;
          var k = 1 + Math.sin(t * 2.4) * 0.16;
          n.mesh.scale.setScalar(k);
        });
        feeders.forEach(function (d, i) {
          d.position.z = -1.2 + Math.sin(t * 0.9 + i) * 0.35;
        });

        var travel = (t * 0.55) % 1;
        packet.position.set(left + travel * reach * step,
          Math.sin(travel * Math.PI) * 0.5, 0);
        packet.visible = reach > 0;

        camera.position.x = Math.sin(t * 0.18) * 1.6;
        camera.lookAt(0, 0, 0);
        renderer.render(view, camera);
      }
      frame();

      var onSize = function () {
        var cw = canvas.clientWidth || w;
        var ch = canvas.clientHeight || h;
        camera.aspect = cw / ch;
        camera.updateProjectionMatrix();
        renderer.setSize(cw, ch, false);
      };
      root.addEventListener('resize', onSize);

      return {
        stop: function () {
          alive = false;
          cancelAnimationFrame(raf);
          root.removeEventListener('resize', onSize);
          try { renderer.dispose(); } catch (e) { /* gone */ }
        }
      };
    }, function () {
      /* No three.js: say so in the space the diagram would have used,
       * rather than leaving a black rectangle. The text below it carries
       * the same information. */
      return null;
    });
  }

  /* ------------------------------------------------------------ open */

  function open(row) {
    build();
    if (openFor && row && openFor.at === row.at && !box.hidden) { close(); return; }
    close();
    openFor = row || null;
    box.hidden = false;

    box.querySelector('.ct-stage').textContent = String((row && row.stage) || 'the console');
    box.querySelector('.ct-detail').textContent = String((row && row.detail) || '');
    var body = box.querySelector('.ct-body');
    body.replaceChildren();
    body.appendChild(make('p', 'ct-wait', 'asking the station what this was…'));
    box.querySelector('.ct-roadwhy').textContent = '';

    if (asking) return;
    asking = true;

    /* `at` IS MILLISECONDS ON THE STATION SIDE. The activity row carries
     * seconds (note_activity stamps int(time.time())), and pipe_detail
     * compares it against a pipeline `ts` in milliseconds with a 2.5
     * second window - so an unconverted value misses by a factor of a
     * thousand, every time, and silently falls back to the newest row of
     * that kind. It would have looked like it worked. */
    var at = row && row.at ? Number(row.at) * 1000 : 0;
    var q = '/api/pipeline/detail?kind=' + encodeURIComponent(roadFor(row && row.stage))
      + (at ? '&at=' + encodeURIComponent(String(at)) : '');

    api().get(q).then(function (detail) {
      asking = false;
      if (box.hidden) return;
      paint(detail || {});
    }, function (err) {
      asking = false;
      body.replaceChildren();
      body.appendChild(make('p', 'ct-wait',
        'The station could not say: ' + ((err && err.message) || err)));
    });
  }

  function paint(detail) {
    var body = box.querySelector('.ct-body');
    body.replaceChildren();

    var road = detail.road || {};
    var why = [];
    if (road.face) why.push(String(road.face));
    if (road.does) why.push(String(road.does));
    box.querySelector('.ct-roadwhy').textContent = why.join(' — ');

    if (!(detail.stages || []).length) {
      box.querySelector('.ct-road').classList.add('flat');
      box.querySelector('.ct-roadwhy').textContent = why.join(' — ')
        || 'the station keeps no road for this kind of line - what it does '
         + 'know is below';
    } else {
      box.querySelector('.ct-road').classList.remove('flat');
    }

    drawRoad(box.querySelector('.ct-canvas'), detail).then(function (made) {
      scene = made;
      if (!made) {
        box.querySelector('.ct-road').classList.add('flat');
      }
    }, function () { scene = null; });

    /* Where it goes, said in words as well as drawn. */
    if (road.goes) {
      var goes = make('p', 'ct-goes');
      goes.appendChild(make('b', '', 'goes '));
      goes.appendChild(make('span', '', String(road.goes)));
      body.appendChild(goes);
    }
    if ((road.uses || []).length) {
      var uses = make('p', 'ct-uses');
      uses.appendChild(make('b', '', 'used by '));
      uses.appendChild(make('span', '', road.uses.join(', ')));
      body.appendChild(uses);
    }

    section(body, 'the line, before and after the tint', tintSection(detail));
    section(body, 'the road, step by step', stagesList(detail));
    section(body, 'how it came to be', promptsList(detail));

    var rate = [];
    if (typeof detail.seen === 'number') rate.push(detail.seen + ' seen');
    if (typeof detail.per_hour === 'number') rate.push(detail.per_hour + ' in the last hour');
    if (detail.writing_now) rate.push('the room is writing now');
    if (rate.length) {
      section(body, 'the last hour, by the minute',
        (function () {
          var wrap = make('div', '');
          var c = chartOf(detail);
          if (c) wrap.appendChild(c);
          wrap.appendChild(make('i', 'ct-rate', rate.join('  ·  ')));
          return wrap;
        })());
    }

    section(body, 'every other time this happened', historyList(detail));
  }

  root.PineConsoleTrace = {
    open: open,
    close: close,
    isOpen: function () { return !!box && !box.hidden; }
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineConsoleTrace;
  }
})(typeof window !== 'undefined' ? window : globalThis);
