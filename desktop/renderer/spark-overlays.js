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
    var timer = null;
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

    function tick() {
      if (busy) return;                 /* never two at once */
      /* NOTHING IS ASKED FOR A SCREEN NOBODY IS ON. rail.js keeps a mounted
       * view in the document at display:none, and a browser tab can be in
       * the background for hours; either way the poll would go on spending
       * the station's socket pool on readouts no one is reading. This is
       * the same discipline the slideshow's own timer runs on. */
      if (document.hidden) return;
      if (typeof active === 'function' && !active()) return;
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
          if (!data.services && last && last.services) {
            data.services = last.services;
            data.ops = last.ops;
            data.marquee = last.marquee;
            data.restartable = last.restartable;
          }
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
        if (timer) return;
        tick();
        timer = setInterval(tick, POLL_MS[mode] || 3000);
      },
      stop: function () {
        if (timer) clearInterval(timer);
        timer = null;
      },
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

  /* TopActivityBanner — what is busy RIGHT NOW. Hidden when nothing is, the
   * way the desktop's is: a banner that is always on screen saying "idle"
   * stops being a signal. */
  function activityWidget() {
    var node = el('div', 'so-w so-activity');
    node.hidden = true;
    var line = el('div', 'so-act-line');
    node.appendChild(line);
    var track = el('div', 'so-track so-act-track');
    var fill = el('div', 'so-fill');
    track.appendChild(fill);
    node.appendChild(track);
    var detail = el('div', 'so-act-detail');
    node.appendChild(detail);
    var prompt = el('div', 'so-act-prompt');
    node.appendChild(prompt);

    return {
      id: 'activity', title: 'Activity', corner: 'tc',
      node: node,
      paint: function (data) {
        var comfy = (data && data.comfy) || {};
        var busy = comfy.running > 0 || comfy.pending > 0;
        node.hidden = !busy;
        if (!busy) return;
        var now = comfy.now || {};
        line.textContent = comfy.running
          ? '◍  ComfyUI is rendering'
          : '◍  ComfyUI has ' + comfy.pending + ' waiting';
        /* HONEST BAR. ComfyUI publishes node-by-node progress over a
         * websocket the desktop app holds open; a poll cannot join that
         * without a second connection to a station this page is already
         * rationing. So the bar is QUEUE DEPTH, and the label says so —
         * rather than a progress bar that is really a guess. */
        var depth = (comfy.running || 0) + (comfy.pending || 0);
        fill.style.width = Math.min(100, depth * 20) + '%';
        fill.style.background = heat(Math.min(100, depth * 20));
        var bits = [];
        if (now.model) bits.push(now.model);
        if (now.size) bits.push(now.size);
        if (now.nodes) bits.push(now.nodes + ' nodes');
        bits.push(comfy.running + ' running · ' + comfy.pending + ' queued');
        if (comfy.last && comfy.last.seconds) {
          bits.push('last took ' + comfy.last.seconds + 's');
        }
        detail.textContent = bits.join('  ·  ');
        prompt.textContent = now.positive || '';
        prompt.hidden = !now.positive;
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
        [['stalling now', s.stalling_now ? String(s.stalling_now) : 'no'],
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

  var DEFAULT = ['activity', 'perf', 'stats', 'services', 'station',
                 'ramring', 'tempring', 'temp'];

  function mount(host, options) {
    if (!host) return null;
    var opts = options || {};
    var mode = opts.mode === 'dashboard' ? 'dashboard' : 'overlay';
    var wanted = opts.widgets || DEFAULT;

    var wrap = el('div', 'so so-' + mode);
    host.appendChild(wrap);

    var built = wanted.map(function (name) {
      var make = BUILDERS[name];
      if (!make) return null;
      var widget = make();
      widget.node.dataset.soId = widget.id;
      if (mode === 'overlay') widget.node.dataset.soCorner = widget.corner;
      wrap.appendChild(widget.node);
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
    wrap.appendChild(switchboard);
    applyHidden();

    var banner = el('div', 'so-banner');
    banner.hidden = true;
    wrap.appendChild(banner);

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
      destroy: function () {
        stop();
        river.stop();
        built.forEach(function (w) { if (w.stop) w.stop(); });
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      }
    };
  }

  root.SparkOverlays = {mount: mount, WIDGETS: Object.keys(BUILDERS)};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.SparkOverlays;
  }
})(typeof window !== 'undefined' ? window : globalThis);
