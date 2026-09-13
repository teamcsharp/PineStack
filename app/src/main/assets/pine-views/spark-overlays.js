/* THE OVERLAYS — window.SparkOverlays.
 *
 * "The slideshow is one thing, but the overlays of the elements is the most
 *  important component... Whenever I would be looking at that slideshow, I
 *  would be getting overlays that would be telling me everything that was
 *  happening with backend components in a detailed fashion."
 *
 * "I wanted it to be a standalone app because this app would be the
 *  management system for interacting with the DGX Spark, but it would also
 *  be something that would be able to pop up inside of the app and also
 *  inside of the application itself, the Electron app as well."
 *
 * So this is ONE module with THREE hosts and no framework:
 *
 *   standalone   GET /spark            — the Spark monitor, any browser
 *   the tablet   the SLIDES view       — drawn over the renders
 *   the desktop  the Electron app      — the same file, same globals
 *
 * `mount(host, {mode})` is the whole contract. `dashboard` lays the widgets
 * out as a grid and owns the screen; `overlay` floats them over whatever is
 * behind, at the desktop application's own corners, draggable, each one
 * toggleable. Nothing here knows which host it is in.
 *
 * WHAT EACH WIDGET IS A PORT OF. These are ~/bin/media-slideshow's classes,
 * and the names are kept so the two can be talked about in one breath:
 *
 *   perf      PerformanceGraph   rolling CPU/RAM/GPU plots + per-core bars
 *   stats     StatsPanel         gauges, per-core, and the NVIDIA section
 *   activity  TopActivityBanner  what is busy right now
 *   services  ServiceLogPanel    each service in turn, with its facts
 *   temp      TempReadout        the hottest sensor, huge, °C/°F flipping
 *   ramring   RamCircle          system RAM as a ring
 *   tempring  TempCircle         the hottest sensor as a ring
 *   station   (new)              the station's own event loop
 *
 * ONE POLL FEEDS ALL OF THEM. The desktop app's panels each tick at 4 Hz off
 * local psutil; every number here is a network read from a station that is
 * also recording a live radio show, and 38 concurrent requests to it
 * measured a 46-second media stall on the tablet. So there is exactly one
 * request in flight, ever, and every widget paints from the same answer.
 *
 * THE HISTORY IS KEPT HERE. Sparklines need a series and the route returns
 * an instant, so each widget keeps its own ring buffer of the last 120
 * samples — which is also why a widget that has just been opened draws a
 * short line rather than a wrong one.
 */
(function (root) {
  'use strict';

  var POLL_MS = {dashboard: 2000, overlay: 3000};
  /* While nobody is looking: how often to check whether they are back. A
   * DOM read and nothing else — the station is not asked anything. */
  var WAKE_CHECK_MS = 4000;
  var HISTORY = 120;            /* the desktop's deque(maxlen=120) */
  var CENSUS_EVERY = 8;         /* polls between service census refreshes */

  /* ---- small helpers ------------------------------------------------- */

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  /* A number that may honestly be absent. The station returns null for
   * anything it could not read — VRAM on a unified-memory board, fan speed
   * on a card with no fan — and every one of those must read as "not
   * reported" rather than as zero. A 0 W GPU is a claim; a dash is not. */
  function num(value, digits) {
    if (value === null || value === undefined || value === '') return null;
    var n = Number(value);
    if (!isFinite(n)) return null;
    return digits === undefined ? n : Number(n.toFixed(digits));
  }

  function show(value, unit, digits) {
    var n = num(value, digits === undefined ? 0 : digits);
    return n === null ? '—' : n + (unit || '');
  }

  function clock(seconds) {
    var s = Math.max(0, Math.round(Number(seconds) || 0));
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    if (d) return d + 'd ' + h + 'h';
    if (h) return h + 'h ' + (m < 10 ? '0' : '') + m + 'm';
    if (m) return m + 'm ' + (s < 10 ? '0' : '') + s + 's';
    return s + 's';
  }

  /* The desktop's colour bands, in its own order: cool → warm → hot. Used
   * for every gauge so a red ring means the same thing wherever it is. */
  function heat(pct) {
    var p = Math.max(0, Math.min(100, Number(pct) || 0));
    if (p < 55) return '#54d18b';
    if (p < 80) return '#e8c65a';
    return '#ff6b7f';
  }

  function tempColour(celsius) {
    var c = Number(celsius);
    if (!isFinite(c)) return '#6d7f8c';
    if (c < 50) return '#54d18b';       /* the desktop's WARM_C */
    if (c < 75) return '#e8c65a';       /* its HOT_C */
    return '#ff6b7f';
  }

  function ring(value) {           /* a deque(maxlen=HISTORY) */
    return {v: [], push: function (n) {
      this.v.push(n === null || n === undefined ? null : Number(n));
      if (this.v.length > HISTORY) this.v.shift();
    }, last: function () { return this.v.length ? this.v[this.v.length - 1] : null; }};
  }

  /* ---- the one request ----------------------------------------------- */

  function feed(mode, active) {
    var listeners = [];
    var fast = null;      /* the polling interval, while someone is looking */
    var watch = null;     /* the cheap "are they back yet" check, while not */
    var onVisibility = null;
    var busy = false;
    var ticks = 0;
    var last = null;
    var failures = 0;

    function get(route) {
      var api = root.pineDesktop;
      if (api && typeof api.get === 'function') return api.get(route);
      return fetch(route, {credentials: 'same-origin'}).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
    }

    /* IS ANYONE LOOKING AT THIS?
     *
     * Three ways the answer is no, and all three have to be asked:
     *   - the whole app or browser tab is in the background (document.hidden)
     *   - rail.js has this view mounted but closed, at display:none
     *   - the operator pressed S and put the overlay layer away
     * The last two arrive through `active`, which the host supplies. */
    function awake() {
      if (typeof document !== 'undefined' && document.hidden) return false;
      if (typeof active === 'function' && !active()) return false;
      return true;
    }

    /* WHAT IS DELIBERATELY NOT IN THAT TEST.
     *
     * Nothing about the station. Not whether it is on air, not whether the
     * operator has paused it, not which Pine Box tab is in front. This is a
     * monitor for the BOX — its cores, its memory, its GPU, what ComfyUI is
     * rendering — and the box goes on doing all of that while the radio is
     * silent. A monitor that stops reporting because the show stopped is
     * useless at exactly the moment somebody is looking to find out why.
     *
     * A station that does not answer is likewise a reason to keep asking,
     * not to give up: a failed poll leaves the interval running and puts a
     * line on screen saying how many have been missed. */

    /* AND WHEN THE ANSWER IS NO, THE TIMER STOPS — it does not keep firing
     * and returning early.
     *
     * "Make sure that we're only pulsing whenever we are in the tab and
     *  we're actually receiving and accessing the information. Otherwise it
     *  needs to sleep and relax."
     *
     * A three-second interval that wakes only to decide it has nothing to
     * do still wakes a sleeping tablet's CPU twenty times a minute, for
     * ever, on a view nobody has open. So the polling interval is CLEARED
     * and replaced by a much slower check that touches nothing but the DOM
     * — no request, no work for the station — until someone comes back. */
    function sleep() {
      if (fast) { clearInterval(fast); fast = null; }
      if (!watch) {
        watch = setInterval(function () {
          if (awake()) wake();
        }, WAKE_CHECK_MS);
      }
    }

    function wake() {
      if (watch) { clearInterval(watch); watch = null; }
      if (fast) return;
      tick();
      fast = setInterval(tick, POLL_MS[mode] || 3000);
    }

    function tick() {
      if (busy) return;                 /* never two at once */
      if (!awake()) { sleep(); return; }
      busy = true;
      /* The census probes five services and runs a real search, so it does
       * not ride every poll — the desktop's own service panel rotated one
       * service every six seconds and lost nothing. */
      var wantCensus = (ticks % CENSUS_EVERY) === 0 || !last || !last.services;
      ticks += 1;
      get('/api/slideshow/backend?census=' + (wantCensus ? 1 : 0))
        .then(function (data) {
          failures = 0;
          /* A poll without the census must not blank the panel that shows
           * it, so the previous answer's rows are carried forward. */
          /* EVERY field that only rides the census poll, or the OpenWebUI
           * panel is blank on seven polls out of eight — which is what it
           * was, and it read as OpenWebUI being unreachable. */
          ['services', 'ops', 'marquee', 'restartable', 'owui'].forEach(
            function (field) {
              if (data[field] === undefined && last && last[field] !== undefined) {
                data[field] = last[field];
              }
            });
          last = data;
          listeners.forEach(function (fn) {
            try { fn(data, null); } catch (err) { /* one widget, not all */ }
          });
        }, function (err) {
          failures += 1;
          listeners.forEach(function (fn) {
            try { fn(last, err); } catch (e2) { /* as above */ }
          });
        }).then(function () { busy = false; });
    }

    return {
      subscribe: function (fn) {
        listeners.push(fn);
        if (last) { try { fn(last, null); } catch (err) { /* ignore */ } }
        return function () {
          var at = listeners.indexOf(fn);
          if (at >= 0) listeners.splice(at, 1);
        };
      },
      start: function () {
        /* The browser tells us the moment a tab is hidden or shown, which
         * is faster and cheaper than waiting for the slow check to notice. */
        if (!onVisibility && typeof document !== 'undefined') {
          onVisibility = function () {
            if (awake()) wake(); else sleep();
          };
          document.addEventListener('visibilitychange', onVisibility);
        }
        if (awake()) wake(); else sleep();
      },
      stop: function () {
        if (fast) clearInterval(fast);
        if (watch) clearInterval(watch);
        fast = null;
        watch = null;
        if (onVisibility && typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', onVisibility);
          onVisibility = null;
        }
      },
      /* For a probe, and for the panel that reports on itself. */
      polling: function () { return !!fast; },
      now: function () { return last; },
      failures: function () { return failures; }
    };
  }

  /* ---- a canvas that survives a hidden parent ------------------------- */

  function canvasFor(node, height) {
    var canvas = el('canvas', 'so-canvas');
    canvas.height = height;
    node.appendChild(canvas);
    return {
      node: canvas,
      /* Sized at paint time, not at build time: a widget mounted into a
       * display:none host has zero width, and a canvas built at zero and
       * never resized stays blank for ever once the host opens. */
      fit: function () {
        var width = canvas.clientWidth || node.clientWidth || 280;
        var dpr = Math.min(2, root.devicePixelRatio || 1);
        var want = Math.round(width * dpr);
        var wantH = Math.round(height * dpr);
        if (canvas.width !== want || canvas.height !== wantH) {
          canvas.width = want;
          canvas.height = wantH;
        }
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return {ctx: ctx, w: width, h: height};
      }
    };
  }

  function plot(ctx, w, h, series, colour, max) {
    var values = series.v;
    if (values.length < 2) return;
    var top = max || 100;
    ctx.beginPath();
    var step = w / (HISTORY - 1);
    var started = false;
    for (var i = 0; i < values.length; i += 1) {
      var value = values[i];
      if (value === null) { started = false; continue; }
      var x = w - (values.length - 1 - i) * step;
      var y = h - (Math.max(0, Math.min(top, value)) / top) * h;
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  /* ================= the widgets ====================================== */
  /* Each returns {id, title, node, paint(data), corner}. `corner` is where
   * the desktop application puts it, and overlay mode honours that. */

  /* PerformanceGraph — the desktop's top-left rolling plot. It graphs the
   * BOX, not this page: the original plots its own process's FPS and RSS,
   * and on a tablet those would be the WebView's, which is not a fact about
   * the Spark. CPU, RAM and GPU utilisation are the three that mean the
   * same thing from here. */
  function perfWidget() {
    var node = el('div', 'so-w so-perf');
    var head = el('div', 'so-head');
    head.appendChild(el('span', 'so-title', 'PERFORMANCE'));
    var legend = el('span', 'so-legend');
    node.appendChild(head);
    head.appendChild(legend);
    var graph = canvasFor(node, 96);
    var coresBox = el('div', 'so-cores');
    node.appendChild(coresBox);
    var foot = el('div', 'so-foot');
    node.appendChild(foot);

    var cpu = ring(), ram = ring(), gpu = ring();
    var bars = [];

    return {
      id: 'perf', title: 'Performance', corner: 'tl',
      node: node,
      paint: function (data) {
        if (!data) return;
        cpu.push(num((data.cpu || {}).pct));
        ram.push(num((data.ram || {}).pct));
        gpu.push(num(((data.gpu || [])[0] || {}).util));

        var fit = graph.fit();
        var ctx = fit.ctx;
        ctx.clearRect(0, 0, fit.w, fit.h);
        /* Grid at 25/50/75, so the eye can read a level off the line
         * without a y-axis taking a third of the width. */
        ctx.strokeStyle = '#1b2630';
        ctx.lineWidth = 1;
        for (var q = 1; q < 4; q += 1) {
          var y = fit.h - (q / 4) * fit.h;
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(fit.w, y); ctx.stroke();
        }
        plot(ctx, fit.w, fit.h, ram, '#65c7da');
        plot(ctx, fit.w, fit.h, cpu, '#54d18b');
        plot(ctx, fit.w, fit.h, gpu, '#e8c65a');

        legend.innerHTML = '';
        [['CPU', '#54d18b', cpu.last()], ['RAM', '#65c7da', ram.last()],
         ['GPU', '#e8c65a', gpu.last()]].forEach(function (row) {
          var tag = el('span', 'so-key');
          var dot = el('i'); dot.style.background = row[1];
          tag.appendChild(dot);
          tag.appendChild(document.createTextNode(
            row[0] + ' ' + (row[2] === null ? '—' : Math.round(row[2]) + '%')));
          legend.appendChild(tag);
        });

        /* PER-CORE, the desktop's own row of little bars. Twenty of them on
         * this box, so they are built once and only their height is
         * touched after that — rebuilding twenty nodes every two seconds on
         * a MediaTek GPU is a layout pass nobody needs. */
        var cores = (data.cpu || {}).per_core || [];
        if (bars.length !== cores.length) {
          coresBox.innerHTML = '';
          bars = cores.map(function () {
            var slot = el('i', 'so-core');
            var fill = el('b');
            slot.appendChild(fill);
            coresBox.appendChild(slot);
            return fill;
          });
        }
        cores.forEach(function (value, i) {
          if (!bars[i]) return;
          bars[i].style.height = Math.max(2, value) + '%';
          bars[i].style.background = heat(value);
        });

        var load = (data.cpu || {});
        foot.textContent = ((data.cpu || {}).cores || cores.length)
          + ' cores · load '
          + show(load.load1, '', 2) + ' / ' + show(load.load5, '', 2)
          + ' / ' + show(load.load15, '', 2)
          + (data.uptime_s ? '  ·  up ' + clock(data.uptime_s) : '');
      }
    };
  }

  /* StatsPanel — the desktop's top-right dashboard. Bar gauges, then the
   * NVIDIA section with every column it draws. */
  function statsWidget() {
    var node = el('div', 'so-w so-stats');
    node.appendChild(el('div', 'so-head')).appendChild(
      el('span', 'so-title', 'STATS'));
    var body = el('div', 'so-body');
    node.appendChild(body);

    function gauge(parent, label, pct, right) {
      var row = el('div', 'so-gauge');
      var top = el('div', 'so-gauge-top');
      top.appendChild(el('span', '', label));
      top.appendChild(el('span', 'so-gauge-val', right));
      row.appendChild(top);
      var track = el('div', 'so-track');
      var fill = el('div', 'so-fill');
      if (pct === null) {
        track.classList.add('unknown');
      } else {
        fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
        fill.style.background = heat(pct);
      }
      track.appendChild(fill);
      row.appendChild(track);
      parent.appendChild(row);
    }

    return {
      id: 'stats', title: 'Stats', corner: 'tr',
      node: node,
      paint: function (data) {
        if (!data) return;
        body.innerHTML = '';
        var ram = data.ram || {};
        var cpu = data.cpu || {};
        gauge(body, 'MEMORY', num(ram.pct),
          show(ram.used_gb, ' GB', 1) + ' / ' + show(ram.total_gb, ' GB', 1));
        gauge(body, 'CPU', num(cpu.pct), show(cpu.pct, '%', 1));
        var disk = data.disk || {};
        gauge(body, 'DISK', num(disk.pct),
          show(disk.free_gb, ' GB free'));
        if (ram.swap_total_gb) {
          gauge(body, 'SWAP',
            ram.swap_total_gb ? (100 * ram.swap_used_gb / ram.swap_total_gb) : null,
            show(ram.swap_used_gb, ' GB', 1));
        }

        (data.gpu || []).forEach(function (card) {
          body.appendChild(el('h5', 'so-section', card.name || 'GPU'));
          gauge(body, 'UTILISATION', num(card.util), show(card.util, '%'));
          if (card.unified_memory) {
            /* SAID, NOT DRAWN EMPTY. A GB10 has no separate VRAM pool; the
             * memory gauge above already is the GPU's memory. */
            var note = el('div', 'so-note',
              'unified memory — the MEMORY gauge above is this board’s too');
            body.appendChild(note);
          } else {
            gauge(body, 'VRAM',
              card.vram_total_mb ? (100 * card.vram_used_mb / card.vram_total_mb) : null,
              show(card.vram_used_mb / 1024, ' GB', 1) + ' / '
              + show(card.vram_total_mb / 1024, ' GB', 1));
          }
          var grid = el('div', 'so-grid');
          [['TEMP', show(card.temp_c, ' °C', 1)],
           ['POWER', card.power_w === null ? 'not reported'
             : show(card.power_w, ' W', 0) + (card.power_cap_w
               ? ' / ' + show(card.power_cap_w, ' W') : '')],
           ['FAN', card.fan_pct === null ? 'not reported' : show(card.fan_pct, '%')],
           ['SM CLOCK', show(card.clock_sm_mhz, ' MHz')],
           ['MEM CLOCK', show(card.clock_mem_mhz, ' MHz')],
           ['MEM BUSY', show(card.mem_util, '%')]
          ].forEach(function (pair) {
            var cell = el('div', 'so-cell');
            cell.appendChild(el('span', 'so-cell-k', pair[0]));
            cell.appendChild(el('span', 'so-cell-v', pair[1]));
            grid.appendChild(cell);
          });
          body.appendChild(grid);
        });

        if (!(data.gpu || []).length) {
          body.appendChild(el('div', 'so-note',
            'nvidia-smi returned nothing — the GPU section is empty rather '
            + 'than invented'));
        }

        var folder = data.folder || {};
        var counters = el('div', 'so-counters');
        [['pictures', folder.total], ['this hour', folder.last_hour],
         ['uptime', data.uptime_s ? clock(data.uptime_s) : '—'],
         ['sensors', (data.thermal || {}).count]
        ].forEach(function (pair) {
          var cell = el('div', 'so-cell');
          cell.appendChild(el('span', 'so-cell-k', pair[0]));
          cell.appendChild(el('span', 'so-cell-v',
            pair[1] === undefined || pair[1] === null ? '—' : pair[1]));
          counters.appendChild(cell);
        });
        body.appendChild(counters);
      }
    };
  }

  /* TopActivityBanner — THE TOP OF THE SCREEN, and the readout the
   * operator asked for by name: "the details of the task that were
   * happening with Comfy UI".
   *
   * It is not "is ComfyUI busy". It is the render itself: its model, its
   * size, its sampler and scheduler and steps and cfg, any LoRAs stacked on
   * it, where it is being saved, how long it has been going, and the prompt
   * text it is working from. All of that comes out of the workflow graph
   * that /queue carries — see spark_overlays.analyze_workflow, which is the
   * desktop application's own reader, node type for node type.
   *
   * IT DOES NOT GO BLANK WHEN NOTHING IS RENDERING. The desktop's banner
   * hides, because the desktop has ten other panels; here it keeps the
   * board and the last few renders on screen, because a panel that shows
   * nothing most of the time teaches you not to look at it. */
  function activityWidget() {
    var node = el('div', 'so-w so-activity');
    var line = el('div', 'so-act-line');
    node.appendChild(line);
    var track = el('div', 'so-track so-act-track');
    var fill = el('div', 'so-fill');
    track.appendChild(fill);
    node.appendChild(track);
    var basis = el('div', 'so-act-basis');
    node.appendChild(basis);
    var detail = el('div', 'so-act-detail');
    node.appendChild(detail);
    var prompt = el('div', 'so-act-prompt');
    node.appendChild(prompt);
    var negative = el('div', 'so-act-negative');
    node.appendChild(negative);
    var board = el('div', 'so-act-board');
    node.appendChild(board);

    function chips(parent, pairs) {
      parent.innerHTML = '';
      pairs.forEach(function (pair) {
        if (pair[1] === null || pair[1] === undefined || pair[1] === ''
            || (Array.isArray(pair[1]) && !pair[1].length)) return;
        var chip = el('span', 'so-fact');
        chip.appendChild(el('i', '', pair[0]));
        chip.appendChild(document.createTextNode(
          Array.isArray(pair[1]) ? pair[1].join(', ') : String(pair[1])));
        parent.appendChild(chip);
      });
    }

    function shortModel(name) {
      return name ? String(name).replace(/\.[a-z0-9]+$/i, '') : '';
    }

    return {
      id: 'activity', title: 'Activity', corner: 'tc',
      node: node,
      paint: function (data) {
        var comfy = (data && data.comfy) || {};
        var now = comfy.now;
        node.classList.toggle('busy', !!now);

        if (!comfy.up) {
          line.textContent = '○  ComfyUI is not answering';
          track.hidden = true;
          basis.textContent = comfy.why || '';
          detail.innerHTML = '';
          prompt.hidden = true;
          negative.hidden = true;
          board.textContent = '';
          return;
        }

        var b = comfy.board || {};
        board.textContent = [
          b.device,
          b.comfyui ? 'ComfyUI ' + b.comfyui : '',
          b.vram_total_gb
            ? 'VRAM ' + b.vram_used_gb + ' / ' + b.vram_total_gb + ' GB' : '',
          b.python ? 'python ' + b.python : ''
        ].filter(Boolean).join('  ·  ');

        if (!now) {
          line.textContent = comfy.pending
            ? '◍  ' + comfy.pending + ' waiting in the queue'
            : '○  ComfyUI is idle';
          track.hidden = true;
          basis.textContent = '';
          prompt.hidden = true;
          negative.hidden = true;
          /* The last few renders and what they cost — which is the thing
           * that makes the NEXT elapsed figure mean something. */
          chips(detail, (comfy.finished || []).slice(0, 4).map(function (row) {
            return [shortModel(row.model) || 'render',
              row.seconds + 's' + (row.size ? ' · ' + row.size : '')];
          }));
          return;
        }

        track.hidden = false;
        line.textContent = '◍  rendering — ' + now.elapsed_s + 's elapsed';
        if (now.progress !== null && now.progress !== undefined) {
          fill.style.width = Math.round(now.progress * 100) + '%';
          fill.style.background = heat(now.progress * 100);
          /* SAID, because it is an estimate and an unlabelled progress bar
           * is a promise. There is no node-by-node figure without holding
           * ComfyUI's websocket open — see the module's header. */
          basis.textContent = 'estimated against the last render of this '
            + 'shape (' + now.expected_s + 's) — ComfyUI reports no '
            + 'progress over HTTP';
        } else {
          fill.style.width = '100%';
          fill.style.background = '#2b3742';
          basis.textContent = 'no previous render of this model, size and '
            + 'step count to measure against yet';
        }

        chips(detail, [
          ['model', shortModel(now.model)],
          ['size', now.size],
          ['steps', now.steps],
          ['cfg', now.cfg],
          ['sampler', now.sampler],
          ['scheduler', now.scheduler],
          ['batch', now.batch > 1 ? now.batch : null],
          ['frames', now.frames],
          ['lora', (now.loras || []).map(shortModel)],
          ['nodes', now.nodes],
          ['into', now.into]
        ]);

        prompt.hidden = !now.positive;
        prompt.textContent = now.positive || '';
        negative.hidden = !now.negative;
        negative.textContent = now.negative ? 'negative: ' + now.negative : '';
      }
    };
  }

  /* THE OPENWEBUI ROLODEX — the other half of what the operator named.
   *
   * The desktop's bottom strip has an OpenWebUI tab that asks a dozen of its
   * endpoints in one tick and lists the lot: version, every model, which are
   * RESIDENT, the chats, the tools, the functions, the knowledge bases, the
   * memories. This is that tab.
   *
   * RESIDENT MODELS COME FIRST, and that is not alphabetical. It is the one
   * figure that says whether the next question is answered now or after a
   * twenty-gigabyte load. */
  function owuiWidget() {
    var node = el('div', 'so-w so-owui');
    var head = el('div', 'so-head');
    head.appendChild(el('span', 'so-title', 'OPEN WEBUI'));
    var version = el('span', 'so-svc-detail');
    head.appendChild(version);
    node.appendChild(head);
    var body = el('div', 'so-body');
    node.appendChild(body);

    return {
      id: 'owui', title: 'Open WebUI', corner: 'bc',
      node: node,
      paint: function (data) {
        var o = (data && data.owui) || null;
        body.innerHTML = '';
        if (!o) {
          version.textContent = '';
          body.appendChild(el('div', 'so-note', 'not read yet'));
          return;
        }
        version.textContent = [
          o.up ? 'answering' : 'not answering',
          o.version ? 'v' + o.version : '',
          o.auth ? 'auth on' : '',
          o.key ? 'key set' : 'no api key'
        ].filter(Boolean).join(' · ');
        if (!o.up) {
          body.appendChild(el('div', 'so-note', o.why || 'no reply'));
          return;
        }

        var resident = o.resident || [];
        body.appendChild(el('h5', 'so-section', 'resident models'));
        if (!resident.length) {
          body.appendChild(el('div', 'so-note',
            'nothing resident — the next question loads a model first'));
        } else {
          resident.forEach(function (m) {
            var row = el('div', 'so-cell');
            row.appendChild(el('span', 'so-cell-k', m.name));
            row.appendChild(el('span', 'so-cell-v', m.vram_gb + ' GB'));
            body.appendChild(row);
          });
        }

        var rows = o.rows || {};
        function count(name) {
          var row = rows[name] || {};
          if (row.count === null || row.count === undefined) {
            return row.state && row.state !== 'ok' ? row.state : '—';
          }
          return row.count;
        }
        body.appendChild(el('h5', 'so-section', 'the shelf'));
        var grid = el('div', 'so-grid');
        [['models', count('models')], ['ollama', count('ollama_models')],
         ['chats', count('chats')], ['tools', count('tools')],
         ['functions', count('functions')], ['knowledge', count('knowledge')],
         ['prompts', count('prompts')], ['memories', count('memories')]
        ].forEach(function (pair) {
          var cell = el('div', 'so-cell');
          cell.appendChild(el('span', 'so-cell-k', pair[0]));
          cell.appendChild(el('span', 'so-cell-v', pair[1]));
          grid.appendChild(cell);
        });
        body.appendChild(grid);

        var chats = o.chats || [];
        if (chats.length) {
          body.appendChild(el('h5', 'so-section', 'latest chats'));
          chats.slice(0, 5).forEach(function (chat) {
            body.appendChild(el('div', 'so-svc-fact',
              chat.title || '(untitled)'));
          });
        }
      }
    };
  }

  /* ServiceLogPanel — the desktop rotated one service every six seconds and
   * showed three lines of its log. There are no container logs from here
   * (the docker proxy is restarts-only by design), so what rotates is the
   * CENSUS: what each service is and what it is doing. */
  function servicesWidget() {
    var node = el('div', 'so-w so-services');
    var head = el('div', 'so-head');
    var title = el('span', 'so-title', 'SERVICES');
    head.appendChild(title);
    var tabs = el('span', 'so-tabs');
    head.appendChild(tabs);
    node.appendChild(head);
    var body = el('div', 'so-body');
    node.appendChild(body);

    var names = [];
    var at = 0;
    var held = false;          /* a touched tab stops the rotation */
    var clock6 = null;

    function paintOne(data) {
      var services = (data && data.services) || {};
      var name = names[at];
      var row = services[name] || {};
      body.innerHTML = '';
      if (!name) {
        body.appendChild(el('div', 'so-note', 'no census yet'));
        return;
      }
      var headline = el('div', 'so-svc-head');
      var dot = el('i', 'so-dot');
      dot.style.background = row.ok ? '#54d18b' : '#ff6b7f';
      headline.appendChild(dot);
      headline.appendChild(el('span', 'so-svc-name', name));
      headline.appendChild(el('span', 'so-svc-detail', row.detail || ''));
      body.appendChild(headline);
      (row.facts || []).slice(0, 6).forEach(function (fact) {
        body.appendChild(el('div', 'so-svc-fact', fact));
      });
      if (!(row.facts || []).length) {
        body.appendChild(el('div', 'so-note',
          'answering, but with nothing to say about itself'));
      }
    }

    return {
      id: 'services', title: 'Services', corner: 'bc',
      node: node,
      paint: function (data) {
        var services = (data && data.services) || {};
        var keys = Object.keys(services).sort();
        if (keys.join('|') !== names.join('|')) {
          names = keys;
          at = Math.min(at, Math.max(0, names.length - 1));
          tabs.innerHTML = '';
          names.forEach(function (name, index) {
            var tab = el('button', 'so-tab', name);
            tab.addEventListener('click', function (event) {
              event.stopPropagation();
              at = index;
              held = true;      /* he chose one: stop moving it */
              paintOne(data);
              paintTabs();
            });
            tabs.appendChild(tab);
          });
        }
        paintTabs();
        paintOne(data);

        if (!clock6) {
          /* SLOT_DURATION_MS, the desktop's own six seconds. */
          clock6 = setInterval(function () {
            if (held || !names.length) return;
            at = (at + 1) % names.length;
            paintTabs();
            paintOne(root.__sparkLast);
          }, 6000);
        }
      },
      stop: function () { if (clock6) clearInterval(clock6); clock6 = null; }
    };

    function paintTabs() {
      [].slice.call(tabs.children).forEach(function (tab, index) {
        tab.classList.toggle('on', index === at);
      });
    }
  }

  /* TempReadout — the hottest sensor as a giant number, flipping °C/°F on
   * the desktop's own four-second cadence. Its roulette spin is not
   * reproduced: that animation costs a repaint of a 120px glyph every frame
   * and this panel shares a GPU with a slideshow. */
  function tempWidget() {
    var node = el('div', 'so-w so-temp');
    var big = el('div', 'so-temp-num', '—');
    node.appendChild(big);
    var unit = el('div', 'so-temp-unit', '');
    node.appendChild(unit);
    var where = el('div', 'so-temp-where', '');
    node.appendChild(where);
    var flip = true;
    setInterval(function () { flip = !flip; }, 4000);

    return {
      id: 'temp', title: 'Temperature', corner: 'br',
      node: node,
      paint: function (data) {
        var hottest = ((data || {}).thermal || {}).hottest;
        var gpu = ((data || {}).gpu || [])[0] || {};
        /* THE TEMPERATURE EVERYONE MEANS IS THE GPU'S (#886) — the board's
         * zones are the fallback, not the headline. */
        var celsius = num(gpu.temp_c);
        var source = celsius === null ? null : 'the GPU';
        if (celsius === null && hottest) {
          celsius = num(hottest.c);
          source = hottest.zone;
        }
        if (celsius === null) {
          big.textContent = '—';
          unit.textContent = '';
          where.textContent = 'no sensor answered';
          return;
        }
        var value = flip ? celsius : (celsius * 9 / 5 + 32);
        big.textContent = Math.round(value);
        big.style.color = tempColour(celsius);
        unit.textContent = flip ? 'Celsius' : 'Fahrenheit';
        where.textContent = source;
      }
    };
  }

  /* RamCircle / TempCircle — the two ring gauges. The desktop's rings are
   * also BUTTONS: the inner disc kills the biggest memory hog, the outer
   * ring flushes and restarts the servers. Neither can be ported — there is
   * no shared PID namespace, so the host's processes are invisible from the
   * station — and the ring says so when it is touched rather than being a
   * dead control that looks live. */
  function ringWidget(id, title, corner, pick) {
    var node = el('div', 'so-w so-ring');
    var canvas = canvasFor(node, 132);
    var label = el('div', 'so-ring-label', '');
    node.appendChild(label);
    var note = el('div', 'so-ring-note');
    note.hidden = true;
    node.appendChild(note);
    var held = null;

    node.addEventListener('click', function (event) {
      event.stopPropagation();
      note.hidden = !note.hidden;
      note.textContent = (held && held.why) || '';
    });

    return {
      id: id, title: title, corner: corner,
      node: node,
      paint: function (data) {
        held = pick(data) || {};
        var fit = canvas.fit();
        var ctx = fit.ctx;
        var size = Math.min(fit.w, fit.h);
        var cx = fit.w / 2, cy = fit.h / 2, r = size / 2 - 10;
        ctx.clearRect(0, 0, fit.w, fit.h);
        ctx.lineWidth = 11;
        ctx.strokeStyle = '#1b2630';
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
        var pct = num(held.pct);
        if (pct !== null) {
          ctx.strokeStyle = held.colour || heat(pct);
          ctx.beginPath();
          ctx.arc(cx, cy, r, -Math.PI / 2,
            -Math.PI / 2 + (Math.max(0, Math.min(100, pct)) / 100) * Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = '#edf3f5';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '600 26px Inter, system-ui, sans-serif';
        ctx.fillText(held.big === undefined ? '—' : String(held.big), cx, cy - 2);
        ctx.font = '10px Inter, system-ui, sans-serif';
        ctx.fillStyle = '#8fa0ad';
        ctx.fillText(held.small || '', cx, cy + 16);
        label.textContent = held.label || title;
      }
    };
  }

  /* The station's own event loop — a backend component like any other, and
   * the only one whose stalls this page can itself be a victim of. */
  function stationWidget() {
    var node = el('div', 'so-w so-station');
    node.appendChild(el('div', 'so-head')).appendChild(
      el('span', 'so-title', 'THE STATION'));
    var body = el('div', 'so-body');
    node.appendChild(body);
    return {
      id: 'station', title: 'Station', corner: 'bl',
      node: node,
      paint: function (data) {
        var s = (data || {}).station || {};
        body.innerHTML = '';
        var grid = el('div', 'so-grid');
        /* The station flattens this to a sentence or an empty string; it
         * used to arrive as a whole stall record, and printing it straight
         * gave "[object Object]" at the one moment it mattered most. */
        [['stalling now', s.stalling_now || 'no'],
         ['stalls', s.stalls === undefined ? '—'
           : s.stalls + ' in ' + Math.round((s.window_s || 0) / 60) + 'm'],
         ['worst', show(s.worst_s, ' s', 1)],
         ['held up', show(s.stalled_s, ' s', 1)]
        ].forEach(function (pair) {
          var cell = el('div', 'so-cell');
          cell.appendChild(el('span', 'so-cell-k', pair[0]));
          cell.appendChild(el('span', 'so-cell-v', pair[1]));
          grid.appendChild(cell);
        });
        body.appendChild(grid);
        if ((s.top || []).length) {
          body.appendChild(el('div', 'so-svc-fact', 'in: ' + s.top.join(', ')));
        }
        /* The report writes its own verdict in English (#1156); it is shown
         * as written rather than re-worded here. */
        if (s.reading) body.appendChild(el('div', 'so-note', s.reading));
      }
    };
  }

  /* ================= mounting ========================================= */

  var BUILDERS = {
    perf: perfWidget,
    stats: statsWidget,
    activity: activityWidget,
    services: servicesWidget,
    owui: owuiWidget,
    temp: tempWidget,
    station: stationWidget,
    ramring: function () {
      return ringWidget('ramring', 'Memory', 'bl', function (data) {
        var ram = (data || {}).ram || {};
        return {
          pct: num(ram.pct), big: ram.pct === null ? '—' : Math.round(ram.pct) + '%',
          small: show(ram.used_gb, '', 0) + ' / ' + show(ram.total_gb, ' GB', 0),
          label: 'MEMORY',
          why: 'The desktop ring also kills the biggest memory hog and '
            + 'flushes the servers. Neither can happen from here: the station '
            + 'runs in a container with no shared PID namespace, so the host’s '
            + 'processes are invisible to it.'
        };
      });
    },
    tempring: function () {
      return ringWidget('tempring', 'Thermal', 'br', function (data) {
        var gpu = ((data || {}).gpu || [])[0] || {};
        var hottest = ((data || {}).thermal || {}).hottest || {};
        var c = num(gpu.temp_c);
        if (c === null) c = num(hottest.c);
        return {
          /* MAX_C = 100 fills the ring, as on the desktop. */
          pct: c === null ? null : c,
          colour: tempColour(c),
          big: c === null ? '—' : Math.round(c) + '°',
          small: (((data || {}).thermal || {}).count || 0) + ' sensors',
          label: 'THERMAL',
          why: 'The desktop ring also kills the tasks contributing to the '
            + 'heat. From here the host’s processes are invisible, so there '
            + 'is nothing to name and nothing to kill.'
        };
      });
    }
  };

  var DEFAULT = ['activity', 'perf', 'stats', 'owui', 'services',
                 'station', 'ramring', 'tempring', 'temp'];

  function mount(host, options) {
    if (!host) return null;
    var opts = options || {};
    var mode = opts.mode === 'dashboard' ? 'dashboard' : 'overlay';
    var wanted = opts.widgets || DEFAULT;

    var wrap = el('div', 'so so-' + mode);
    host.appendChild(wrap);

    /* REGIONS, NOT CORNERS — and this is the whole of "nothing overlaps and
     * nothing is trimmed off screen".
     *
     * The first version pinned each widget to the corner its desktop
     * counterpart uses. On a 1920x1080 desk that is fine; on a 1340x800
     * tablet two widgets share every bottom corner, the panels ran off the
     * right edge under the rail, and rotating to portrait made all of it
     * worse. Absolute corners cannot be made safe by nudging them, because
     * the failure is structural: nothing stops two of them occupying the
     * same pixels.
     *
     * So the layer is a GRID of four regions — a left rail, a right rail, a
     * top band and a bottom band — with the middle left transparent for
     * whatever is behind. Grid regions cannot overlap by construction, and
     * each one SCROLLS, so a column too tall for the screen is reachable
     * rather than cut off. Portrait collapses the two rails into one band,
     * because 800px of width cannot carry two 296px columns and still show
     * a picture.
     *
     * The regions are `pointer-events: none` with the widgets `auto`, so the
     * gaps between them still belong to the slideshow underneath — a swipe
     * that lands on bare picture still changes the picture. */
    var regions = null;
    if (mode === 'overlay') {
      regions = {};
      /* The top band is always its own child of the grid. The other three
       * live inside a BAND, which is `display: contents` in landscape — so
       * the grid sees the three regions directly and places them left,
       * right and bottom — and becomes a real scrolling container in
       * portrait, where all three fold into one strip along the foot. One
       * element, two behaviours, and no widget ever changes parent. */
      regions.t = el('div', 'so-region so-region-t');
      wrap.appendChild(regions.t);
      var band = el('div', 'so-band');
      wrap.appendChild(band);
      ['l', 'r', 'b'].forEach(function (key) {
        var region = el('div', 'so-region so-region-' + key);
        band.appendChild(region);
        regions[key] = region;
      });
    }

    /* Which region each of the desktop application's corners becomes. */
    var REGION_OF = {tl: 'l', bl: 'l', tr: 'r', br: 'r', tc: 't', bc: 'b'};

    var built = wanted.map(function (name) {
      var make = BUILDERS[name];
      if (!make) return null;
      var widget = make();
      widget.node.dataset.soId = widget.id;
      if (regions) {
        widget.node.dataset.soCorner = widget.corner;
        (regions[REGION_OF[widget.corner] || 'l']).appendChild(widget.node);
      } else {
        wrap.appendChild(widget.node);
      }
      return widget;
    }).filter(Boolean);

    /* WHICH ONES HE LEFT ON. Per-glass, so localStorage rather than the
     * station's settings — and wrapped, because storage throws outright in
     * some contexts and a remembered layout is not worth a dead panel. */
    var MEMORY = 'sparkOverlays:' + mode;
    var hidden = {};
    try { hidden = JSON.parse(localStorage.getItem(MEMORY) || '{}') || {}; }
    catch (err) { hidden = {}; }

    function applyHidden() {
      built.forEach(function (widget) {
        widget.node.classList.toggle('off', !!hidden[widget.id]);
      });
      try { localStorage.setItem(MEMORY, JSON.stringify(hidden)); }
      catch (err) { /* fine */ }
    }

    /* The switchboard: one chip per widget, so every readout can be put
     * away and brought back. In overlay mode it is the only furniture that
     * is always on screen. */
    var switchboard = el('div', 'so-switch');
    built.forEach(function (widget) {
      var chip = el('button', 'so-chip', widget.title);
      chip.addEventListener('click', function (event) {
        event.stopPropagation();
        hidden[widget.id] = !hidden[widget.id];
        chip.classList.toggle('on', !hidden[widget.id]);
        applyHidden();
      });
      chip.classList.toggle('on', !hidden[widget.id]);
      switchboard.appendChild(chip);
    });
    /* In the flow of the top band, not floating: a control that covers the
     * readout it controls is the same fault as two overlapping panels. */
    (regions ? regions.t : wrap).appendChild(switchboard);
    applyHidden();

    var banner = el('div', 'so-banner');
    banner.hidden = true;
    (regions ? regions.t : wrap).appendChild(banner);

    var river = feed(mode, opts.active);
    var stop = river.subscribe(function (data, err) {
      root.__sparkLast = data;
      if (err) {
        banner.hidden = false;
        banner.textContent = 'the station did not answer ('
          + (err.message || err) + ') — showing the last reading, '
          + river.failures() + ' misses';
      } else {
        banner.hidden = true;
      }
      if (!data) return;
      built.forEach(function (widget) {
        try { widget.paint(data); } catch (e) { /* one widget, not all */ }
      });
    });
    river.start();

    return {
      node: wrap,
      widgets: built,
      data: function () { return river.now(); },
      polling: function () { return river.polling(); },
      destroy: function () {
        stop();
        river.stop();
        built.forEach(function (w) { if (w.stop) w.stop(); });
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      }
    };
  }


  /* ================= the pop-up ======================================= */

  /* THE SC STACK AS A POP-UP, over whatever is already on screen.
   *
   * "...while also being able to access it as a pop up inside of Pinebox
   *  tab."
   *
   * The SLIDES view is full-bleed: it replaces the panel. That is right when
   * the readouts are what you are there for, and wrong when you are working
   * the deck and want to glance at the GPU without losing your place. So
   * this is a real floating window — drag it by its bar, resize it from the
   * corner, put it away — and it hosts the SAME module in dashboard mode.
   *
   * ONE AT A TIME, and calling popup() again closes it. A second monitor
   * polling the same station on the same glass would double the traffic for
   * nothing, and the toggle is what a button on a rail expects.
   *
   * WHERE IT SITS IS REMEMBERED, per glass, in localStorage — a pop-up that
   * comes back to the middle of the screen every time is one you end up
   * dragging every time. Clamped on restore, because a window remembered at
   * the edge of a landscape tablet is off the side of a portrait one.
   */
  var POPUP_MEMORY = 'sparkPopup';
  var popupLive = null;

  function popupBox() {
    var box = {x: null, y: null, w: 560, h: 460};
    try {
      var held = JSON.parse(localStorage.getItem(POPUP_MEMORY) || 'null');
      if (held && typeof held === 'object') {
        ['x', 'y', 'w', 'h'].forEach(function (k) {
          if (typeof held[k] === 'number') box[k] = held[k];
        });
      }
    } catch (err) { /* a remembered corner is not worth a broken window */ }
    /* Never larger than the glass, never smaller than useful, never off it. */
    box.w = Math.max(280, Math.min(box.w, root.innerWidth - 16));
    box.h = Math.max(220, Math.min(box.h, root.innerHeight - 16));
    if (box.x === null) box.x = Math.max(8, (root.innerWidth - box.w) / 2);
    if (box.y === null) box.y = Math.max(8, (root.innerHeight - box.h) / 3);
    box.x = Math.max(0, Math.min(box.x, root.innerWidth - box.w));
    box.y = Math.max(0, Math.min(box.y, root.innerHeight - box.h));
    return box;
  }

  function rememberBox(box) {
    try { localStorage.setItem(POPUP_MEMORY, JSON.stringify(box)); }
    catch (err) { /* fine */ }
  }

  function popup(options) {
    if (popupLive) {
      popupLive.close();
      return null;
    }
    var opts = options || {};
    var box = popupBox();

    var frame = el('div', 'so-popup');
    frame.style.left = box.x + 'px';
    frame.style.top = box.y + 'px';
    frame.style.width = box.w + 'px';
    frame.style.height = box.h + 'px';

    var bar = el('div', 'so-popup-bar');
    bar.appendChild(el('span', 'so-popup-title', opts.title || 'SC STACK'));
    var buttons = el('span', 'so-popup-buttons');
    bar.appendChild(buttons);
    frame.appendChild(bar);

    var body = el('div', 'so-popup-body');
    frame.appendChild(body);
    var grip = el('div', 'so-popup-grip');
    frame.appendChild(grip);
    document.body.appendChild(frame);

    var layer = mount(body, {
      mode: 'dashboard',
      /* A pop-up that has been put away asks the station nothing. */
      active: function () { return !!frame.parentNode; }
    });

    function button(label, hint, onPress) {
      var node = el('button', 'so-popup-btn', label);
      node.title = hint;
      node.addEventListener('click', function (event) {
        event.stopPropagation();
        onPress();
      });
      buttons.appendChild(node);
      return node;
    }

    var wide = false;
    button('⤢', 'Fill the screen, or come back', function () {
      wide = !wide;
      frame.classList.toggle('wide', wide);
      if (!wide) {
        frame.style.left = box.x + 'px';
        frame.style.top = box.y + 'px';
        frame.style.width = box.w + 'px';
        frame.style.height = box.h + 'px';
      }
    });
    /* Straight through to the standalone application, for when a glance
     * turns into a session. */
    button('↗', 'Open the SC Stack on its own', function () {
      try { root.open('/spark?pictures=1', '_blank'); } catch (err) { /* blocked */ }
    });
    button('✕', 'Put it away', function () { api.close(); });

    /* ---- dragging and resizing, by pointer so a finger works --------- */

    function drags(handle, onMove) {
      handle.addEventListener('pointerdown', function (event) {
        if (wide) return;
        event.preventDefault();
        var startX = event.clientX;
        var startY = event.clientY;
        var from = {x: frame.offsetLeft, y: frame.offsetTop,
                    w: frame.offsetWidth, h: frame.offsetHeight};
        handle.setPointerCapture(event.pointerId);
        function move(ev) { onMove(ev.clientX - startX, ev.clientY - startY, from); }
        function up(ev) {
          handle.releasePointerCapture(ev.pointerId);
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', up);
          box = {x: frame.offsetLeft, y: frame.offsetTop,
                 w: frame.offsetWidth, h: frame.offsetHeight};
          rememberBox(box);
        }
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
      });
    }

    drags(bar, function (dx, dy, from) {
      /* Clamped to the glass while dragging, not only on restore: a window
       * dragged off the top has no bar left to drag it back by. */
      var x = Math.max(0, Math.min(from.x + dx, root.innerWidth - from.w));
      var y = Math.max(0, Math.min(from.y + dy, root.innerHeight - 40));
      frame.style.left = x + 'px';
      frame.style.top = y + 'px';
    });

    drags(grip, function (dx, dy, from) {
      frame.style.width = Math.max(280,
        Math.min(from.w + dx, root.innerWidth - from.x)) + 'px';
      frame.style.height = Math.max(220,
        Math.min(from.h + dy, root.innerHeight - from.y)) + 'px';
    });

    var api = {
      node: frame,
      layer: layer,
      data: function () { return layer.data(); },
      polling: function () { return layer.polling(); },
      close: function () {
        if (!frame.parentNode) return;
        /* The layer first: it owns the timer, and a detached frame with a
         * live poll is exactly the leak this whole file is careful about. */
        try { layer.destroy(); } catch (err) { /* going anyway */ }
        frame.parentNode.removeChild(frame);
        popupLive = null;
      }
    };
    popupLive = api;
    return api;
  }

  root.SparkOverlays = {mount: mount, popup: popup,
    isPopupOpen: function () { return !!popupLive; },
    WIDGETS: Object.keys(BUILDERS)};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.SparkOverlays;
  }
})(typeof window !== 'undefined' ? window : globalThis);
