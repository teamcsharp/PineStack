/* The Digital feed's canonical roulette listing and typewriter, shared by
 * the feed, replay tiles, and the configurable System3 message tile overlay.
 * Recorded reels, landing values, DOM classes, and timing stay identical. */
(function (root) {
  'use strict';
  var BUILD = {per: 1800, one: [0.08, 0.18, 0.60, 0.06], two: [0.08, 0.12, 0.27, 0.06, 0.12, 0.27, 0.06],
    rejEach: 260, rejBase: 140, rejCap: 0.4, rejMax: 6, fail: 420, between: 40, hold: 1500};
  var FAMILY_COLORS = {CTS: '#8ac6ac', ES: '#f0a6ca', RS: '#87bfff', IRS: '#ffb86b', FL: '#c4a1ee',
    SPEAKERBOX: '#e7bf78', SFX: '#7fe0d6', TOPIC: '#9be15d', SFXGUY: '#ffd479', LINE: '#b8c4ff',
    MEMORY: '#d9c9a3', STATION: '#9aa9ab', GRAPH: '#9be15d',
    MEASURE: '#ff6b8b', SFXREACT: '#ffd479', CUTIN: '#c4a1ee', MINIROUND: '#87bfff', HOLD: '#d9c9a3'};

  function typeCount(previous, fraction, length) {
    var n = Math.floor(fraction * length + 0.0001);
    if (n < previous) n = previous;
    if (previous >= 0 && n - previous > 3) n = previous + Math.ceil((n - previous) * 0.3);
    return n;
  }

  function mvStageOf(ev, name) {
    var st = (ev && ev.stages) || [];
    for (var i = 0; i < st.length; i += 1) if (st[i] && st[i].stage === name) return st[i];
    return null;
  }
  function mvReel(stg, fallbackDice) {
    var cands = (stg && stg.candidates) || [];
    var opts = [], hit = 0, mvW = [];   /* [msgroll] the raffle weights too */
    for (var i = 0; i < cands.length; i += 1) {
      var c = cands[i] || {};
      opts.push(String(c.label || c.id || ''));
      mvW.push(Math.max(0, Number(c.weight) || 0));   /* [msgroll] */
      if (String(c.id) === String(stg.selected)) hit = i;
    }
    var rrRej = mvRrRejOf(stg);                /* [rollplay] the candidates a rule removed: they pop in, then go grey */
    return {rej: rrRej, dice: stg && stg.draw && stg.draw.dice != null ? stg.draw.dice : fallbackDice,
      opts: opts, hit: hit, label: opts[hit] || String((stg && stg.selected) || ''),
      of: opts.length, stage: String((stg && stg.stage) || ''), weights: mvW};   /* [msgroll] */
  }
  function mvDecisionRow(ev) {
    var st = (ev && ev.stages) || [];
    var reels = [], drawn = null, i;
    for (i = 0; i < st.length; i += 1) {
      var s = st[i] || {};
      if (s.draw && s.draw.dice != null && !drawn) drawn = s;
      if (s.stage !== 'table' && (s.candidates || []).length > 1 && s.selected != null) reels.push(s);
    }
    var rng = ev && ev.rng && ev.rng.dice != null ? ev.rng.dice : null;
    if (!drawn && rng === null) return null;                /* decided by a rule: not a roll */
    var dice = drawn ? drawn.draw.dice : rng;
    var cat = mvStageOf(ev, 'category');
    var item = mvStageOf(ev, 'item');
    var main = null, sub = null;
    if (cat && (cat.candidates || []).length > 1) { main = cat; sub = item && (item.candidates || []).length > 1 ? item : null; }
    else if (item && (item.candidates || []).length > 1) {
      main = item;
      var k = reels.indexOf(item);
      sub = k >= 0 && reels[k + 1] ? reels[k + 1] : null;
    } else { main = reels[0] || null; sub = reels[1] || null; }
    var sel = (ev && ev.selected) || {};
    var landed = String(sel.label || sel.id || (drawn && drawn.selected) || '');
    if (ev.family === 'GRAPH' && (ev.meta || {}).turn_credit) landed += ' · +1 turn restored';
    var rrTs = mvStageOf(ev, 'table'), rrT0 = rrTs && (rrTs.candidates || [])[0];   /* [msgroll] the table's own name */
    var mainReel = main ? mvReel(main, dice) : {dice: dice, opts: [landed], hit: 0, label: landed, of: 1, stage: ''};
    if (ev.family === 'GRAPH' && (ev.meta || {}).turn_credit) {
      mainReel.label = landed;
      mainReel.opts[mainReel.hit] = landed;
    }
    return {fam: String(ev.family || ''), table: String(sel.table || ev.family || ''), tableLabel: rrT0 ? String(rrT0.label || '') : '',
      event: String(ev.event_id || ''),
      main: mainReel,
      sub: sub ? mvReel(sub, null) : null, failed: mvRrFailed(ev), vrej: mvRrVerdicts(ev),   /* [rollplay] */
      material: sel.material || null,                                       /* [research-pop] */
      prompt: sel.prompt_row != null ? {words: String(sel.prompt || ''), row: String(sel.prompt_row || ''),
        used: !!sel.in_prompt} : null};                                     /* [prompt-share] */
  }
  function mvCounted(fam, table, one, two) {
    var mk = function (x) {
      if (!x) return null;
      return {dice: x.dice != null ? x.dice : null, opts: [String(x.label || '')], hit: 0,
        label: String(x.label || ''), index: Number(x.index) || 0, of: Number(x.of) || 0, counted: true};
    };
    return {fam: fam, table: table, event: '', main: mk(one), sub: mk(two)};
  }
  var RR_REJ_MAX = 6;
  function mvRrRejOf(stg) {
    var out = [];
    ((stg && stg.excluded) || []).forEach(function (x) {
      if (!x || out.length >= RR_REJ_MAX) return;
      out.push({label: String(x.label || x.id || ''), why: 'rejected: ' + String(x.why || 'a rule removed it')});
    });
    return out;
  }
  function mvRrVerdicts(ev) {
    var out = [];
    ((ev && ev.stages) || []).forEach(function (st) {
      ((st && st.verdicts) || []).forEach(function (v) {
        if (!v || v.eligible !== false || out.length >= RR_REJ_MAX) return;
        out.push({label: String(v.label || v.id || ''), why: 'not eligible: ' + String(v.why || 'its rule said no')});
      });
    });
    return out;
  }
  function mvRrFailed(ev) {
    var sel = (ev && ev.selected) || {};
    var id = String(sel.id || '').toUpperCase();
    if (id !== 'PASS' && id !== 'NONE') return null;
    var gate = null;
    ((ev && ev.stages) || []).forEach(function (st) { if (st && st.threshold != null && !gate) gate = st; });
    var d = gate && gate.draw ? gate.draw.dice : null;
    return {why: 'failed: ' + String(sel.label || 'the roll returned nothing')
      + (gate && gate.rule ? ' - ' + String(gate.rule) : '') + (d != null ? ' (rolled ' + d + ')' : '')};
  }
  function mvRrMatchRej(m) {
    var out = [];
    if (!m) return out;
    var removed = m.removed || {};
    Object.keys(removed).forEach(function (k) {
      var n = Number(removed[k]) || 0;
      if (n > 0 && out.length < RR_REJ_MAX) out.push({label: n + ' removed', why: 'rejected by a rule: ' + k + ' (' + n + ' clip' + (n === 1 ? '' : 's') + ')'});
    });
    var won = Number(m.score);
    (m.candidates || []).forEach(function (x) {
      if (!x || out.length >= RR_REJ_MAX) return;
      var sc = Number(x.score);
      if (!(isFinite(won) && isFinite(sc) && sc < won)) return;   /* a tie may be the one drawn: never greyed */
      var words = [].concat(x.line || [], x.context || [], x.senses || [], x.folder_words || []).slice(0, 3);
      out.push({label: String(x.folder || 'a clip') + (words.length ? ' - ' + words.join(', ') : ''),
        why: 'lost: scored ' + sc.toFixed(2) + ', the pick ' + won.toFixed(2)});
    });
    var tied = Number(m.tied) || 0;
    if (tied > 1 && out.length < RR_REJ_MAX) out.push({label: (tied - 1) + ' tied', why: 'tied at ' + (isFinite(won) ? won.toFixed(2) : '?') + ' - not drawn'});
    return out;
  }

  /* Pure adapters for recorded events: never draw new randomness or infer a
     selection. The order is the Digital feed's ES-first, stable sequence. */
  function decisionRows(events) {
    return (events || []).map(mvDecisionRow).filter(function (row) { return !!row; })
      .sort(function (a, b) { return (a.fam === 'ES' ? 0 : 1) - (b.fam === 'ES' ? 0 : 1); });
  }
  function countedRow(fam, table, one, two, metadata) {
    var row = mvCounted(fam, table, one, two);
    var extra = metadata || {};
    ['event', 'tableLabel', 'failed', 'vrej', 'material', 'prompt', 'match', 'why'].forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(extra, key)) row[key] = extra[key];
    });
    if (row.main && one && one.rej) row.main.rej = one.rej.slice();
    if (row.sub && two && two.rej) row.sub.rej = two.rej.slice();
    if (row.sub && extra.match && typeof extra.match === 'object') {
      row.sub.rej = (row.sub.rej || []).concat(mvRrMatchRej(extra.match));
    }
    return row;
  }

  function rowKey(row) {
    return String(row.event || '') || [row.fam, row.table, row.main && row.main.dice,
      row.main && row.main.label, row.sub && row.sub.dice, row.sub && row.sub.label].join('|');
  }

  function createRenderer(adapters) {
    adapters = adapters || {};
    var document = root.document;
    var make = adapters.make || function (tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = String(text);
      return node;
    };
    var MV_FAM = adapters.familyColors || FAMILY_COLORS;
    var MV_BUILD = BUILD;
    var RR_WIN = 24;
    var mvRrPopWire = adapters.wireEntry || function () {};
    var mvMatchChip = adapters.matchChip;
    var mvMerge = adapters.merge || defaultMerge;
    function defaultMerge(a, b) {
      var out = {}, k;
      for (k in (a || {})) if (Object.prototype.hasOwnProperty.call(a, k)) out[k] = a[k];
      for (k in (b || {})) if (Object.prototype.hasOwnProperty.call(b, k) && b[k] != null && b[k] !== '') out[k] = b[k];
      return out;
    }

    function mvRrStep(reel, sub) {
      var el = make('div', 'sp-rr-step ' + (sub ? 'sp-rr-sub' : 'sp-rr-cat'));
      var die = make('span', 'sp-rr-die', '#');
      var wheel = make('span', 'sp-rr-wheel');
      var list = make('span', 'sp-rr-list');
      wheel.appendChild(list);
      var of = make('i', 'sp-rr-of', '');
      el.appendChild(die);
      el.appendChild(wheel);
      el.appendChild(of);
      el.style.display = 'none';
      var rej = mvRrRejChips(el, reel);          /* [rollplay] */
      var opts = (reel && reel.opts && reel.opts.length) ? reel.opts : [String((reel && reel.label) || '')];
      var hit = Math.max(0, Math.min(opts.length - 1, Number(reel && reel.hit) || 0));
      var w = (reel && reel.weights && reel.weights.length === opts.length) ? reel.weights : null;
      var sum = 0, i;
      for (i = 0; i < opts.length; i += 1) sum += w ? Math.max(0, Number(w[i]) || 0) : 1;
      var hOf = function (k) {
        if (!w || !sum) return RR_WIN;
        var share = Math.max(0, Number(w[k]) || 0) / sum;
        return Math.round(Math.max(16, Math.min(44, RR_WIN * 0.6 + share * opts.length * RR_WIN * 0.55)));
      };
      /* the reel: the real list (twice when short), then up to the rolled one */
      var seq = [];
      var passes = reel && reel.counted ? 0 : (opts.length > 40 ? 1 : 2);
      for (var p = 0; p < passes; p += 1) for (i = 0; i < opts.length; i += 1) seq.push(i);
      for (i = 0; i <= hit; i += 1) seq.push(i);
      if (seq.length < 4) { seq = [hit, hit, hit].concat(seq); }            /* a list of one still spins a little */
      var y = 0, target = 0;
      seq.forEach(function (k, n) {
        var h = hOf(k);
        var cell = make('span', 'sp-rr-cell' + (n === seq.length - 1 ? ' hit' : ''), reel && reel.counted && n === seq.length - 1 ? reel.label : opts[k]);
        cell.style.height = h + 'px';
        cell.style.lineHeight = h + 'px';
        list.appendChild(cell);
        if (n === seq.length - 1) target = y - (RR_WIN - h) / 2;
        y += h;
      });
      var landed = reel && reel.counted && reel.of
        ? (reel.index + ' of ' + reel.of) : (opts.length > 1 ? (hit + 1) + ' of ' + opts.length : 'the only one');
      /* Reserve the real count's width while it waits: landing never
         narrows an already visible reel or shifts its neighbours. */
      of.textContent = landed;
      of.style.visibility = 'hidden';
      el.setAttribute('data-state', 'waiting');
      return {el: el, die: die, list: list, wheel: wheel, of: of, target: target, reel: reel || {}, landedOf: landed, rej: rej};   /* [rollplay] */
    }

    function mvBuildFit(tables, from, ms, at) {
      var fresh = tables.slice(from || 0);
      if (!fresh.length || !(ms > 0)) return at;
      var start = fresh[0].at;
      var gaps = MV_BUILD.between * fresh.length;
      var span = at - start - gaps;
      var want = ms - MV_BUILD.hold - gaps;
      if (!(span > 0) || !(want > 0)) return at;
      var k = want / span;
      if (Math.abs(k - 1) < 0.002) return at;
      var a = start;
      fresh.forEach(function (T) {
        ['dIn', 'dRej', 'dDie', 'dSpin', 'dPop', 'dRej2', 'dDie2', 'dSpin2', 'dPop2', 'dFail'].forEach(function (f) {
          T[f] = (T[f] || 0) * k;
        });
        T.at = a;
        T.end = a + T.dIn + T.dRej + T.dDie + T.dSpin + T.dPop + T.dRej2 + T.dDie2 + T.dSpin2 + T.dPop2 + T.dFail;
        a = T.end + MV_BUILD.between;
      });
      return a;
    }

    function mvRrReserve(sheet) {
      /* Every row keeps its natural reel geometry. A future compact-result
         height reservation would create blank space and skip active rows. */
      if (sheet && sheet.box) sheet.box.style.minHeight = '';
    }

    function mvRrTable(cur, r, rows, index) {
      var t = make('div', 'sp-rr-t');
      t.style.setProperty('--fam', MV_FAM[r.fam] || '#68ced9');
      t.style.display = 'none';
      t.setAttribute('data-state', 'waiting');
      var head = make('div', 'sp-rr-head');
      head.appendChild(make('b', '', r.table || r.fam));
      if (r.tableLabel && r.tableLabel !== r.table) head.appendChild(make('span', '', r.tableLabel));
      t.appendChild(head);
      var cat = mvRrStep(r.vrej && r.vrej.length ? mvMerge(r.main, {rej: (r.main.rej || []).concat(r.vrej)}) : r.main, false);
      t.appendChild(cat.el);
      mvRrPopWire(cat.el, rows, index, 'main');
      var sub = r.sub ? mvRrStep(r.sub, true) : null;
      if (sub) { t.appendChild(sub.el); mvRrPopWire(sub.el, rows, index, 'sub'); }
      mvRrFoldNote(head, r, cat, sub);
      if (r.match && typeof mvMatchChip === 'function') mvMatchChip(head, cur);
      return {el: t, head: head, cat: cat, sub: sub, r: r, landed: false};
    }

    function mvRrSchedule(tables, from, cur, budgetMs, start) {
      var fresh = tables.slice(from), n = Math.max(1, fresh.length);
      var per = Math.max(1100, Math.min(2400, (Number(budgetMs) > 0 ? Number(budgetMs) : 6000) / n));
      var fit = cur && cur.buildFit;
      if (fit && fit.ms > 0) per = MV_BUILD.per;
      var at = start;
      fresh.forEach(function (T) {
        var two = !!T.sub;
        T.at = at;
        T.dIn = per * 0.08;
        T.dDie = per * (two ? 0.12 : 0.18);
        T.dSpin = per * (two ? 0.27 : 0.6);
        T.dPop = per * 0.06;
        T.dDie2 = two ? per * 0.12 : 0;
        T.dSpin2 = two ? per * 0.27 : 0;
        T.dPop2 = two ? per * 0.06 : 0;
        T.dRej = mvRrRejMs(T.cat, per);
        T.dRej2 = T.sub ? mvRrRejMs(T.sub, per) : 0;
        T.dFail = T.r.failed ? 420 : 0;
        T.end = at + T.dIn + T.dRej + T.dDie + T.dSpin + T.dPop + T.dRej2 + T.dDie2 + T.dSpin2 + T.dPop2 + T.dFail;
        at = T.end + MV_BUILD.between;
      });
      if (fit && fit.ms > 0) at = mvBuildFit(tables, Math.max(from, Number(fit.from) || 0), fit.ms, at);
      return at;
    }

    function mvRrSheet(cur, rows, budgetMs) {
      var box = make('div', 'sp-rr');
      var recorded = (rows || []).slice();
      var tables = recorded.map(function (r, i) {
        var T = mvRrTable(cur, r, recorded, i);
        box.appendChild(T.el);
        return T;
      });
      var at = mvRrSchedule(tables, 0, cur, budgetMs, 0);
      box.setAttribute('data-state', 'waiting');
      return {box: box, rows: recorded, tables: tables, rolled: at, total: at + MV_BUILD.hold, now: '', elapsed: 0};
    }

    function mvRrAppend(sheet, freshRows, cur, budgetMs) {
      if (!sheet || !(freshRows || []).length) return sheet;
      var from = sheet.tables.length;
      var actual = cur && cur.appendAt != null ? Number(cur.appendAt) : Number(sheet.elapsed);
      var start = Math.max(sheet.rolled, isFinite(actual) ? actual : 0);
      (freshRows || []).forEach(function (r) {
        var index = sheet.rows.length;
        sheet.rows.push(r);
        var T = mvRrTable(cur, r, sheet.rows, index);
        sheet.tables.push(T);
        sheet.box.appendChild(T.el);
      });
      sheet.rolled = mvRrSchedule(sheet.tables, from, cur, budgetMs, start);
      sheet.total = sheet.rolled + MV_BUILD.hold;
      sheet.now = '';
      sheet.box.classList.remove('results');
      sheet.box.setAttribute('data-now', '');
      sheet.box.setAttribute('data-state', 'rolling');
      return sheet;
    }

    function mvRrOut(x) { x = Math.max(0, Math.min(1, x)); return 1 - Math.pow(1 - x, 3.2); }

    function mvRrStepAt(step, dieE, dDie, spinE, dSpin, popE, dPop) {
      if (dieE < 0) return 'wait';
      if (step.el.style.display === 'none') step.el.style.display = '';
      var r = step.reel || {};
      var face = r.dice == null ? '-' : (dieE >= dDie ? String(r.dice) : String(1 + ((Number(r.dice || 0) * 37 + Math.floor(dieE / 70) * 53) % 100)));
      if (step.die.textContent !== face) step.die.textContent = face;
      step.die.classList.toggle('rolling', dieE < dDie);
      if (dieE < dDie) { step.el.setAttribute('data-state', 'die'); return 'die'; }
      var k = spinE >= dSpin ? 1 : mvRrOut(spinE / dSpin);
      var tr = 'translateY(' + (-Math.round(k * step.target)) + 'px)';
      if (step.list.style.transform !== tr) step.list.style.transform = tr;
      step.wheel.classList.toggle('spinning', spinE >= 0 && spinE < dSpin);
      if (spinE < dSpin) { step.el.setAttribute('data-state', 'spin'); return 'spin'; }
      /* The winner stays in this very reel; the timing's landing hold
         never scales the box or creates a second results presentation. */
      step.wheel.classList.remove('pop');
      step.of.style.visibility = '';
      step.el.setAttribute('data-state', 'landed');
      return popE < dPop ? 'pop' : 'done';
    }

    function mvRrResults(sheet) {
      sheet.box.style.display = '';
      sheet.tables.forEach(mvRrQuiet);
      sheet.box.classList.add('results');
      sheet.box.setAttribute('data-state', 'landed');
      sheet.now = 'results';
      sheet.box.setAttribute('data-now', 'results');
    }

    function mvRrQuiet(T) {
      if (T.landed) return;
      T.el.style.display = '';
      T.el.style.opacity = '1';
      T.el.classList.remove('arriving');
      T.el.classList.add('landed');
      T.el.setAttribute('data-state', 'landed');
      if (T.r && T.r.failed) { T.el.classList.add('sp-rr-failed'); T.el.title = T.r.failed.why; }
      mvRrRejAt(T.cat, 1e9, T.dRej || 1);
      if (T.sub) mvRrRejAt(T.sub, 1e9, T.dRej2 || 1);
      [T.cat, T.sub].forEach(function (step) {
        if (!step) return;
        step.el.style.display = '';
        step.el.setAttribute('data-state', 'landed');
        var face = step.reel.dice == null ? '-' : String(step.reel.dice);
        if (step.die.textContent !== face) step.die.textContent = face;
        var tr = 'translateY(' + (-Math.round(step.target)) + 'px)';
        if (step.list.style.transform !== tr) step.list.style.transform = tr;
        step.of.style.visibility = '';
        step.die.classList.remove('rolling');
        step.wheel.classList.remove('spinning');
        step.wheel.classList.remove('pop');
      });
      T.landed = true;
    }

    /* Explicit replay keeps the same reel/option/inspector nodes and the
       recorded schedule. It only clears presentation state. */
    function mvRrReset(sheet) {
      if (!sheet) return sheet;
      sheet.box.style.display = '';
      sheet.box.style.minHeight = '';
      sheet.box.classList.remove('results');
      sheet.box.setAttribute('data-state', 'waiting');
      sheet.box.setAttribute('data-now', '');
      sheet.now = '';
      sheet.elapsed = 0;
      sheet.tables.forEach(function (T) {
        T.landed = false;
        T.el.style.display = 'none';
        T.el.style.opacity = '';
        T.el.classList.remove('landed');
        T.el.classList.remove('arriving');
        T.el.classList.remove('sp-rr-failed');
        T.el.title = '';
        T.el.setAttribute('data-state', 'waiting');
        [T.cat, T.sub].forEach(function (step) {
          if (!step) return;
          step.el.style.display = 'none';
          step.el.setAttribute('data-state', 'waiting');
          step.die.textContent = '#';
          step.die.classList.remove('rolling');
          step.list.style.transform = '';
          step.wheel.classList.remove('spinning');
          step.wheel.classList.remove('pop');
          step.of.style.visibility = 'hidden';
          (step.rej || []).forEach(function (chip) {
            chip.style.display = 'none';
            chip.classList.remove('pop');
            chip.classList.remove('gone');
          });
        });
      });
      return sheet;
    }

    function mvRrAt(sheet, ms, skip) {
      sheet.elapsed = skip ? Math.max(sheet.rolled, Number(ms) || 0) : Math.max(0, Number(ms) || 0);
      if (!skip && ms >= sheet.rolled) { if (sheet.now !== 'results') mvRrResults(sheet); return 'results'; }
      var now = '';
      sheet.box.setAttribute('data-state', 'rolling');
      sheet.tables.forEach(function (T, i) {
        var e = skip ? 1e9 : ms - T.at;
        if (e < 0) { if (T.el.style.display !== 'none') T.el.style.display = 'none'; return; }
        var finished = e >= T.end - T.at;
        if (finished) { mvRrQuiet(T); return; }
        if (T.el.style.display === 'none') T.el.style.display = '';
        T.el.style.opacity = String(Math.min(1, e / Math.max(1, T.dIn)));
        T.el.setAttribute('data-state', 'rolling');
        var a0 = e - T.dIn;
        var q1 = mvRrRejAt(T.cat, a0, T.dRej || 0);
        var a = a0 - (T.dRej || 0);
        var s1 = q1 === 'rej' ? 'rej' : mvRrStepAt(T.cat, a, T.dDie, a - T.dDie, T.dSpin, a - T.dDie - T.dSpin, T.dPop);
        var s2 = 'none';
        if (T.sub) {
          var b0 = a - T.dDie - T.dSpin - T.dPop;
          var q2 = mvRrRejAt(T.sub, b0, T.dRej2 || 0);
          var b = b0 - (T.dRej2 || 0);
          s2 = q2 === 'rej' ? 'rej' : (q2 === 'wait' ? 'wait' : mvRrStepAt(T.sub, b, T.dDie2, b - T.dDie2, T.dSpin2, b - T.dDie2 - T.dSpin2, T.dPop2));
        }
        var failing = !!T.r.failed && e >= T.end - T.at - (T.dFail || 0);
        if (T.r.failed) T.el.classList.toggle('sp-rr-failed', failing);
        now = i + ':' + (e < T.dIn ? 'table' : failing ? 'failed' : (s2 !== 'none' && s2 !== 'wait' ? 'sub-' + s2 : 'cat-' + s1));
      });
      sheet.now = now;
      if (sheet.box.getAttribute('data-now') !== now) sheet.box.setAttribute('data-now', now);
      return now;
    }

    function mvRrRejChips(el, reel) {
      var list = (reel && reel.rej) || [];
      if (!list.length) return [];
      el.classList.add('sp-rr-has-rej');
      var box = make('span', 'sp-rr-rej');
      var out = [];
      list.forEach(function (x) {
        var c = make('span', 'sp-rr-rejc', x.label);
        c.title = x.why;
        c.setAttribute('aria-disabled', 'true');
        c.style.display = 'none';
        box.appendChild(c);
        out.push(c);
      });
      el.appendChild(box);
      return out;
    }

    function mvRrRejMs(step, per) {
      var n = step && step.rej ? step.rej.length : 0;
      return n ? Math.min(per * 0.4, 260 * n + 140) : 0;
    }

    function mvRrRejAt(step, e, d) {
      var c = (step && step.rej) || [];
      if (!c.length || !d) return 'none';
      if (e < 0) return 'wait';
      if (step.el.style.display === 'none') step.el.style.display = '';
      var gap = d / c.length;
      for (var k = 0; k < c.length; k += 1) {
        var t = e - k * gap;
        var on = t >= 0, grey = t >= gap * 0.55;
        if (c[k].style.display !== (on ? '' : 'none')) c[k].style.display = on ? '' : 'none';
        c[k].classList.toggle('pop', on && !grey);
        c[k].classList.toggle('gone', grey);
      }
      return e < d ? 'rej' : 'none';
    }

    function mvRrFoldNote(line, r, cat, sub) {
      var n = ((cat && cat.rej) || []).length + ((sub && sub.rej) || []).length;
      if (n) {
        var why = [].concat((cat && cat.rej) || [], (sub && sub.rej) || []).map(function (c) { return c.textContent + ' - ' + c.title; });
        var tag = make('i', 'sp-rr-rejn', n + ' rejected');
        tag.title = why.join('\n');
        line.appendChild(tag);
      }
      if (r && r.failed) line.title = r.failed.why;
    }

    return {step: mvRrStep, buildFit: mvBuildFit, reserve: mvRrReserve, sheet: mvRrSheet, append: mvRrAppend, reset: mvRrReset, out: mvRrOut, stepAt: mvRrStepAt, results: mvRrResults, quiet: mvRrQuiet, at: mvRrAt, rejectionChips: mvRrRejChips, rejectionMs: mvRrRejMs, rejectionAt: mvRrRejAt, foldNote: mvRrFoldNote};
  }

  const TYPING_CPS=60;
  const DEFAULTS={mode:'hold',fontSize:12,opacity:.85,rollSpeed:1,typingSpeed:1,followPlayback:true,fadeDelay:4};
  function tileOptions(value){
    const options={...DEFAULTS,...value};
    options.mode=['hold','fade','history'].includes(options.mode)?options.mode:'hold';
    for(const [key,min,max] of [['fontSize',8,28],['opacity',0,1],['rollSpeed',.25,4],['typingSpeed',.25,4],['fadeDelay',0,60]])options[key]=Number.isFinite(Number(options[key]))?Math.max(min,Math.min(max,Number(options[key]))):DEFAULTS[key];
    options.followPlayback=options.followPlayback!==false;return options;
  }
  /* One current message, using the Digital feed's actual roulette renderer.
     The caller supplies station beats; this tile owns no media or poller.
     mount(into, {load(row, payload), clock, wireEntry, options}) expects
     load to return normalized Digital rows and an answered flag; clock is
     milliseconds aligned with station.stream_now.at (seconds). receive takes
     {now, rows, station}; configure/visible/dispose manage its lifetime.
     onLayout receives rendered viewport {width,height,element,item,current,
     phase,history,active,visible}; measure/requestLayout expose that sizing. */
  function mount(into,adapters){
    adapters=adapters||{};const document=into.ownerDocument||root.document,view=adapters.window||document.defaultView||root;
    const node=adapters.make||function(tag,cls,text){const element=document.createElement(tag);if(cls)element.className=cls;if(text!=null)element.textContent=String(text);return element;};
    const clock=typeof adapters.clock==='function'?adapters.clock:()=>Date.now();
    const stage=node('div','pip-system3-stage');stage.setAttribute('role','log');stage.setAttribute('aria-label','System3 message tile');stage.setAttribute('tabindex','0');
    const navigation=node('nav','pip-system3-navigation');navigation.setAttribute('aria-label','Message history');
    const back=node('button','pip-system3-previous','‹'),forward=node('button','pip-system3-next','›');
    for(const [button,label] of [[back,'Previous message'],[forward,'Next message']]){button.type='button';button.setAttribute('aria-label',label);button.title=label;navigation.appendChild(button);}
    for(const [button,points] of [[back,'10 3.5 4 8 10 12.5'],[forward,'6 3.5 12 8 6 12.5']])button.innerHTML='<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><polyline points="'+points+'" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><line x1="4" y1="8" x2="13" y2="8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    into.classList.add('pip-system3-host');into.appendChild(navigation);
    const empty=node('p','pip-system3-empty','Waiting for an on-air message');stage.appendChild(empty);into.appendChild(stage);
    const core=createRenderer({...adapters,make:node,wireEntry(element,rows,index,which){
      adapters.wireEntry?.(element,rows,index,which);
      // These run after the original inspector opens, even when it stops bubbling.
      element.addEventListener('click',inspectPopup);
      element.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' ')inspectPopup();});
    }});
    let card=null,payload=null,currentId='',active=true,dead=false,raf=0,lastFrame=0,revision=0,follow=true,handAt=0,held=false,heldTiming=null,externalHold=false,hovered=false,popup=null,pointer=null;
    let settings=tileOptions(adapters.options);const history=[];const HISTORY_LIMIT=12;
    const archive=new Map();const REVIEW_LIMIT=100;let latestId='',reviewing=false;
    function navigationState(){const ids=[...archive.keys()],index=ids.indexOf(currentId);return {index,total:ids.length,canPrevious:index>0,canNext:index>=0&&index<ids.length-1};}
    function updateNavigation(){const state=navigationState();back.disabled=!state.canPrevious;forward.disabled=!state.canNext;stage.setAttribute('aria-live',reviewing?'off':'polite');}
    function record(value,live){
      const rows=value.rows||[],liveId=String(live?.id||'');
      for(const row of rows.concat(live?[live]:[])){
        if(!row?.id||row.music||/^(upcoming|queued|pending|next)$/i.test(String(row.lcdStatus||'')))continue;
        const id=String(row.id);let saved=archive.get(id);
        if(!saved){saved={row:{...row},data:null,card:null,scrollTop:0,wordScrollTop:0,rollScrollTop:0};archive.set(id,saved);}else saved.row={...saved.row,...row};
      }
      if(liveId&&!live.music&&archive.has(liveId)){latestId=liveId;const saved=archive.get(liveId);archive.delete(liveId);archive.set(liveId,saved);}
      while(archive.size>REVIEW_LIMIT){const id=[...archive.keys()].find(key=>key!==currentId&&key!==latestId);if(!id)break;const old=archive.get(id);if(old.card&&!history.includes(old.card))old.card.element.remove();archive.delete(id);}
      updateNavigation();
    }
    function saveCard(value){
      const saved=archive.get(value?.id);if(!saved)return;saved.card=value.data?value:null;saved.data=value.data||saved.data;saved.scrollTop=Number(stage.scrollTop)||0;saved.wordScrollTop=Number(value.words.scrollTop)||0;saved.rollScrollTop=Number(value.rolls.scrollTop)||0;
      const cached=[...archive.values()].filter(entry=>entry.card);
      while(cached.length>HISTORY_LIMIT){const index=cached.findIndex(entry=>entry.card!==card);if(index<0)break;const old=cached.splice(index,1)[0];if(!history.includes(old.card))old.card.element.remove();old.card=null;}
    }
    function settleReview(){
      if(!reviewing||!card||!card.data)return;
      if(card.sheet)core.results(card.sheet);card.words.hidden=false;card.words.textContent=card.text;card.typed=card.text.length;complete();
      card.element.hidden=false;card.element.style.opacity='';follow=false;lastFrame=0;
      const saved=archive.get(card.id);if(saved){stage.scrollTop=saved.scrollTop;card.words.scrollTop=saved.wordScrollTop;card.rolls.scrollTop=saved.rollScrollTop;}
    }
    function navigate(direction){
      if(dead||!active)return false;const ids=[...archive.keys()],index=ids.indexOf(currentId),id=ids[index+direction];
      if(index<0||!id)return false;
      reviewing=true;follow=false;heldTiming=null;currentId=id;start(archive.get(id).row);updateNavigation();return true;
    }
    function previous(){return navigate(-1);}function next(){return navigate(1);}
    function resumeLatest(){
      if(!reviewing)return;reviewing=false;follow=true;heldTiming=null;
      const saved=archive.get(latestId);
      if(saved&&latestId!==currentId){currentId=latestId;start(saved.row);}
      if(active&&payload)receive(payload);updateNavigation();requestLayout();wake();
    }
    back.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();previous();});
    forward.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();next();});
    stage.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();event.stopPropagation();navigate(event.key==='ArrowLeft'?-1:1);}});
    let layoutRaf=0,layoutStamp='';
    /* Layout sizes include each rendered card and its font zoom. Overflow
       stays within the separate reading and roulette panes. */
    function measure(){
      return {width:Math.ceil(Math.max(Number(stage.scrollWidth)||0,Number(stage.offsetWidth)||0)),
        height:Math.ceil(Math.max(Number(stage.scrollHeight)||0,Number(stage.offsetHeight)||0)),
        element:stage,item:card?.element||null,current:currentId,phase:card?.phase||'waiting',history:history.length,
        active,reviewing,navigation:navigationState(),visible:active&&!document.hidden&&(!card||!card.element.hidden)};
    }
    function notifyLayout(){
      if(dead||!stage.isConnected)return;
      const info=measure(),stamp=[info.width,info.height,info.current,info.phase,info.history,info.active,info.visible,info.reviewing,settings.fontSize,settings.mode].join(':');
      if(stamp===layoutStamp)return;layoutStamp=stamp;
      if(typeof adapters.onLayout==='function')adapters.onLayout(info);
    }
    function requestLayout(){
      if(dead||layoutRaf||typeof adapters.onLayout!=='function')return;
      if(document.hidden){notifyLayout();return;}
      layoutRaf=view.requestAnimationFrame(()=>{layoutRaf=0;notifyLayout();});
    }
    function paused(){return settings.followPlayback&&payload?.station?.paused===true;}
    function wake(){if(!dead&&active&&!document.hidden&&!paused()&&(!reviewing||card?.phase==='loading')&&!raf)raf=view.requestAnimationFrame(frame);}
    function followCurrent(){
      if(reviewing||held||!card)return;
      // History may scroll between messages; neither pane scrolls the article.
      if(follow&&settings.mode==='history'){
        const a=stage.getBoundingClientRect(),b=card.element.getBoundingClientRect();
        stage.scrollTop+=b.top-a.top;
      }
      if(card.wordFollow)card.words.scrollTop=Math.max(0,(Number(card.words.scrollHeight)||0)-(Number(card.words.clientHeight)||0));
      if(card.rollFollow&&card.phase==='roll'){
        const table=card.sheet.tables.find(t=>card.rollMs>=t.at&&card.rollMs<t.end)||card.sheet.tables[card.sheet.tables.length-1];
        if(table){
          const child=table.sub&&card.sheet.now.includes('sub-')?table.sub.el:table.el;
          const a=card.rolls.getBoundingClientRect(),b=child.getBoundingClientRect(),scale=settings.fontSize/12;
          if(b.bottom>a.bottom-8)card.rolls.scrollTop+=(b.bottom-a.bottom+8)/scale;
        }
      }
    }
    function bindPane(value,pane,key){
      let touchedAt=0;
      const hand=()=>{touchedAt=Date.now();value[key]=false;};
      ['wheel','touchstart','touchmove','pointerdown','keydown'].forEach(name=>pane.addEventListener(name,hand,{passive:true}));
      pane.addEventListener('scroll',()=>{if(Date.now()-touchedAt<1200)value[key]=pane.scrollTop+pane.clientHeight>=pane.scrollHeight-16;},{passive:true});
    }
    function playbackTiming(){
      if(!card||!payload)return null;const stream=payload.station?.stream_now;
      const recorded=(stream?.rows||[]).find(row=>String(row.id||row.line_id||'')===card.id);
      if(held&&!recorded&&String(payload.now?.id||'')!==card.id)return null;
      const timed=recorded||card.row;
      if(stream?.at==null||timed.from==null||timed.until==null)return null;
      const from=Number(timed.from),until=Number(timed.until),at=Number(stream.at);
      return Number.isFinite(from)&&Number.isFinite(until)&&until>from&&Number.isFinite(at)?{from,until,at}:null;
    }
    function playbackFraction(){
      const timing=heldTiming||playbackTiming();if(!timing)return null;
      return Math.max(0,Math.min(1,(clock()/1000-timing.at-timing.from)/(timing.until-timing.from)));
    }
    function syncHold(){
      const on=externalHold||hovered||!!popup;
      if(dead||held===on)return;held=on;heldTiming=held?playbackTiming():null;lastFrame=0;
      if(!held){follow=true;if(!popup)resumeLatest();}
      if(card){card.element.hidden=false;card.element.style.opacity='';if(card.phase==='done')card.doneAt=Date.now();}
      if(!held&&active&&payload){receive(payload);followCurrent();}
      requestLayout();wake();
    }
    function hold(on){externalHold=!!on;syncHold();}
    function rememberPointer(event){if(event.pointerType!=='touch')pointer={x:event.clientX,y:event.clientY};}
    function enter(event){if(event.pointerType==='touch')return;rememberPointer(event);hovered=true;syncHold();}
    function leave(event){rememberPointer(event);hovered=false;if(!popup)resumeLatest();syncHold();}
    function inspectPopup(){
      const next=document.getElementById?.('spRrPop');if(!next)return;
      popup=next;popup.__system3MessageOwner=stage;syncHold();
      popupObserver?.observe(document.body,{childList:true});
    }
    const popupObserver=typeof view.MutationObserver==='function'?new view.MutationObserver(()=>{
      if(!popup)return;
      const next=document.getElementById('spRrPop');
      if(next){popup=next;popup.__system3MessageOwner=stage;return;}
      popup=null;popupObserver.disconnect();
      const target=pointer&&document.elementFromPoint?.(pointer.x,pointer.y);
      hovered=target?into.contains(target):!!into.matches?.(':hover');
      if(!hovered)resumeLatest();syncHold();
    }):null;
    into.addEventListener('pointerenter',enter);into.addEventListener('pointerleave',leave);
    document.addEventListener('pointermove',rememberPointer,{passive:true});
    function complete(){if(!card||card.phase==='done')return;card.phase='done';card.doneAt=Date.now();card.element.classList.add('pip-system3-complete');card.words.classList.remove('typing');}
    function sizeWords(value=card){
      if(!value)return;if(value.sizer.textContent!==value.text)value.sizer.textContent=value.text;
      const height=Number(value.sizer.offsetHeight)||0;
      if(height>0)value.words.style.setProperty('--pip-message-words-height',height+'px');
    }
    function typeWords(dt=0){
      if(!card||reviewing||card.phase==='done')return;
      // A finished short reply never banks time while its reels continue rolling.
      card.typingMs=Math.min(card.text.length*1000/TYPING_CPS,card.typingMs+Math.max(0,dt)*settings.typingSpeed);
      const typed=card.still?card.text.length:Math.min(card.text.length,Math.max(card.typed,card.text?1:0,Math.floor(card.typingMs*TYPING_CPS/1000+0.0001)));
      card.words.hidden=false;
      if(typed!==card.typed){card.typed=typed;card.words.textContent=card.text.slice(0,typed);}
      card.words.classList.toggle('typing',typed<card.text.length);
    }
    function frame(now){
      raf=0;if(reviewing&&card?.phase!=='loading'){lastFrame=0;return;}if(paused()){lastFrame=0;return;}if(dead||!active||document.hidden||!card||!stage.isConnected)return;
      if(lastFrame&&now-lastFrame<33){wake();return;}const dt=lastFrame?Math.max(0,now-lastFrame):0;lastFrame=now;
      // Text uses the same character rate during loading, reels, and replies.
      typeWords(dt);
      if(card.phase==='loading'){if(!card.loading&&Date.now()>=card.retryAt)load(card);followCurrent();requestLayout();wake();return;}
      if(card.phase==='roll'){
        card.rollMs+=dt*settings.rollSpeed;
        // Reels start at their own first frame; late data must not skip to audio progress.
        core.at(card.sheet,card.rollMs,card.still);followCurrent();
        if(card.still||card.rollMs>=card.sheet.total){core.results(card.sheet);card.phase='typing';card.words.hidden=false;}
      }
      if(card.phase==='typing'){
        if(card.typed>=card.text.length)complete();followCurrent();
      }
      if(card.phase==='done'&&settings.mode==='fade'&&!held){
        const age=Date.now()-card.doneAt-settings.fadeDelay*1000;
        if(age>=0){card.element.style.opacity=String(Math.max(0,1-age/450));if(age>=450){card.element.hidden=true;requestLayout();return;}}
        wake();
      }else if(card.phase!=='done')wake();
      requestLayout();
    }
    /* Station ticks trigger a refresh only when the recorded roster or its
       decision material changes. Playback clocks/status never cause a poll. */
    function materialStamp(value,row){
      const rows=value?.rows||[];
      const record=r=>[r?.id||r?.line_id||'',r?.cid||r?.conversation_id||'',r?.tid||r?.turn_id||'',
        r?.event_id||r?.decision_event_id||'',r?.decision_events||null,r?.sfx_roll||null,
        r?.material||null,r?.match_why||r?.sfx_match_why||'',r?.origin||null];
      return JSON.stringify([record(row),rows.map(record)]);
    }
    function load(loadingCard){
      if(loadingCard.loading||dead)return;
      loadingCard.loading=true;
      const ticket=revision,source=payload,attemptStamp=loadingCard.sourceStamp,row=loadingCard.row;
      Promise.resolve().then(()=>reviewing&&archive.get(loadingCard.id)?.data||adapters.load(row,source,{live:!reviewing})).then(data=>{
        if(dead||ticket!==revision||card!==loadingCard||(reviewing&&loadingCard.data))return;
        if(!data||data.answered===false){loadingCard.retryAt=Date.now()+1000;if(loadingCard.phase==='loading')loadingCard.status.textContent='Waiting for recorded System 3 rolls';return;}
        const initial=!loadingCard.data,recorded=data.rows||[];
        const duration=Number(loadingCard.row.until)-Number(loadingCard.row.from);
        const requested=typeof adapters.rollBudget==='function'?Number(adapters.rollBudget(recorded,loadingCard.row)):0;
        const budget=requested>0&&Number.isFinite(requested)?Math.min(3600000,requested):(duration>0?Math.max(3000,Math.min(9000,duration*700)):6000);
        loadingCard.data=data;loadingCard.loadedStamp=attemptStamp;loadingCard.retryAt=0;
        if(initial){
          loadingCard.rows=recorded;loadingCard.rolls.replaceChildren();
          loadingCard.sheet=recorded.length?core.sheet({},recorded,budget):null;
          if(loadingCard.sheet){loadingCard.rows=loadingCard.sheet.rows;loadingCard.sheet.box.classList.add('sp-rr-keep');loadingCard.rolls.appendChild(loadingCard.sheet.box);loadingCard.phase='roll';core.at(loadingCard.sheet,0,false);}
          else{loadingCard.status.textContent='No System3 roulette recorded for this message';loadingCard.rolls.appendChild(loadingCard.status);loadingCard.phase='typing';loadingCard.words.hidden=false;}
        }else{
          const seen=new Set(loadingCard.rows.map(rowKey));
          const fresh=recorded.filter(record=>{const key=rowKey(record);if(seen.has(key))return false;seen.add(key);return true;});
          if(fresh.length){
            const restarting=loadingCard.phase==='done';
            if(loadingCard.sheet)core.append(loadingCard.sheet,fresh,{appendAt:loadingCard.rollMs},budget);
            else{loadingCard.status.remove();loadingCard.sheet=core.sheet({},fresh,budget);loadingCard.sheet.box.classList.add('sp-rr-keep');loadingCard.rolls.appendChild(loadingCard.sheet.box);}
            loadingCard.rows=loadingCard.sheet.rows;
            loadingCard.phase='roll';loadingCard.doneAt=0;loadingCard.element.hidden=false;loadingCard.element.style.opacity='';loadingCard.element.classList.remove('pip-system3-complete');
            /* The visible prefix and typing time remain intact while the new
               rows roll. Only fresh rows receive a new timeline. */
            core.at(loadingCard.sheet,loadingCard.rollMs,loadingCard.still);
            if(restarting)lastFrame=0;followCurrent();
          }
        }
        loadingCard.element.dataset.rows=String(loadingCard.rows.length);const saved=archive.get(loadingCard.id);if(saved)saved.data=data;settleReview();requestLayout();wake();
      }).catch(()=>{if(!dead&&ticket===revision&&card===loadingCard){if(loadingCard.phase==='loading')loadingCard.status.textContent='System3 rolls unavailable; retrying';loadingCard.retryAt=Date.now()+1500;}}).finally(()=>{
        loadingCard.loading=false;
        if(!dead&&ticket===revision&&card===loadingCard){
          if(active&&!reviewing&&loadingCard.sourceStamp!==attemptStamp)load(loadingCard);
          requestLayout();wake();
        }
      });
    }
    function start(row){
      revision++;if(raf)view.cancelAnimationFrame(raf);raf=0;lastFrame=0;
      if(card){saveCard(card);if(!reviewing&&settings.mode==='history'&&card.phase==='done'){card.element.classList.add('pip-system3-history');card.element.style.opacity='';card.element.hidden=false;history.push(card);}else card.element.remove();}
      if(reviewing||settings.mode!=='history')history.splice(0).forEach(old=>old.element.remove());
      while(history.length>=HISTORY_LIMIT)history.shift().element.remove();empty.remove();
      const saved=archive.get(String(row.id));
      if(reviewing&&saved?.card){
        card=saved.card;card.element.classList.remove('pip-system3-history');stage.appendChild(card.element);sizeWords(card);settleReview();stage.scrollTop=saved.scrollTop;follow=false;
        if(!card.data&&!card.loading)load(card);updateNavigation();requestLayout();wake();return;
      }
      const element=node('article','pip-system3-message'),rolls=node('div','pip-system3-rolls'),status=node('p','pip-system3-status','Loading recorded System 3 rolls'),words=node('div','pip-system3-words'),sizer=node('div','pip-system3-words-measure');
      element.dataset.line=String(row.id);words.setAttribute('tabindex','0');words.setAttribute('role','region');words.setAttribute('aria-label','Reply text');rolls.setAttribute('tabindex','0');rolls.setAttribute('role','region');rolls.setAttribute('aria-label','System3 roulette');words.hidden=false;words.classList.toggle('typing',!!row.text);rolls.appendChild(status);sizer.setAttribute('aria-hidden','true');element.append(words,rolls,sizer);stage.appendChild(element);
      card={id:String(row.id),row:{...row},text:String(row.text||''),element,rolls,status,words,sizer,rows:[],sourceStamp:materialStamp(payload,row),loadedStamp:null,phase:'loading',loading:false,retryAt:0,rollMs:0,typingMs:0,typed:0,doneAt:0,wordFollow:true,rollFollow:true,still:!!view.matchMedia?.('(prefers-reduced-motion: reduce)').matches};
      bindPane(card,words,'wordFollow');bindPane(card,rolls,'rollFollow');follow=!reviewing;stage.scrollTop=0;updateNavigation();sizeWords();typeWords();load(card);requestLayout();wake();
    }
    function receive(value){
      if(dead)return;payload=value;if(paused())lastFrame=0;
      const live=value.now||(value.rows||[]).find(r=>r.lcdStatus==='Playing'&&!r.music);
      record(value,live);if(!active||reviewing)return;
      const row=held&&currentId&&String(live?.id||'')!==currentId
        ?(value.rows||[]).find(r=>String(r.id||'')===currentId&&!r.music)||card?.row:live;
      const id=row?.id&&!row.music?String(row.id):'';
      if(id&&id!==currentId){currentId=id;start(row);}
      else if(id&&card){card.row={...card.row,...row};const text=String(row.text||'');if(text&&text!==card.text){card.text=text;sizeWords();card.typed=Math.min(card.typed,text.length);card.words.textContent=text.slice(0,card.typed);if(card.phase==='done'){card.phase='typing';lastFrame=0;card.element.classList.remove('pip-system3-complete');card.element.hidden=false;card.element.style.opacity='';}}card.sourceStamp=materialStamp(value,card.row);if(!card.loading&&Date.now()>=card.retryAt&&(card.phase==='loading'||card.sourceStamp!==card.loadedStamp))load(card);}
      if(held&&(!heldTiming||String(live?.id||'')===currentId))heldTiming=playbackTiming()||heldTiming;
      requestLayout();wake();
    }
    function configure(value){
      const previousMode=settings.mode;settings=tileOptions(value);if(card&&settings.mode==='fade'&&previousMode!=='fade'&&card.phase==='done'){card.doneAt=Date.now();card.element.hidden=false;card.element.style.opacity='';}stage.style.setProperty('--pip-message-font',settings.fontSize+'px');stage.style.setProperty('--pip-message-scale',String(settings.fontSize/12));stage.style.setProperty('--pip-message-opacity',String(settings.opacity));
      stage.classList.toggle('pip-system3-stage-history',settings.mode==='history');for(const value of history)sizeWords(value);sizeWords();if(settings.mode!=='history')history.splice(0).forEach(old=>old.element.remove());
      if(card&&settings.mode!=='fade'){card.element.hidden=false;card.element.style.opacity='';}lastFrame=0;requestLayout();wake();
    }
    function hand(event){if(card&&(card.words.contains(event.target)||card.rolls.contains(event.target)))return;handAt=Date.now();follow=false;}['wheel','touchstart','touchmove','pointerdown','keydown'].forEach(name=>stage.addEventListener(name,hand,{passive:true}));
    stage.addEventListener('scroll',()=>{if(Date.now()-handAt<1200)follow=stage.scrollTop+stage.clientHeight>=stage.scrollHeight-16;},{passive:true});
    function onVisible(){lastFrame=0;if(document.hidden&&layoutRaf){view.cancelAnimationFrame(layoutRaf);layoutRaf=0;}requestLayout();wake();}document.addEventListener('visibilitychange',onVisible);
    const resize=typeof view.ResizeObserver==='function'?new view.ResizeObserver(()=>{for(const value of history)sizeWords(value);sizeWords();followCurrent();requestLayout();wake();}):null;resize?.observe(stage);
    updateNavigation();configure(settings);
    return {receive,configure,hold,previous,next,measure,requestLayout,element:stage,visible(on){const waking=!active&&!!on;active=!!on;if(!active){externalHold=false;hovered=false;popup=null;held=false;heldTiming=null;reviewing=false;popupObserver?.disconnect();}if(waking&&card){card.element.hidden=false;card.element.style.opacity='';if(card.phase==='done')card.doneAt=Date.now();}if(!active&&raf){view.cancelAnimationFrame(raf);raf=0;}lastFrame=0;if(active&&payload)receive(payload);requestLayout();wake();},dispose(){dead=true;revision++;if(raf)view.cancelAnimationFrame(raf);raf=0;if(layoutRaf)view.cancelAnimationFrame(layoutRaf);layoutRaf=0;resize?.disconnect();popupObserver?.disconnect();into.removeEventListener?.('pointerenter',enter);into.removeEventListener?.('pointerleave',leave);document.removeEventListener('pointermove',rememberPointer);document.removeEventListener('visibilitychange',onVisible);stage.remove();navigation.remove();archive.clear();},state(){return {reviewing,navigation:navigationState(),current:currentId,phase:card?.phase||'waiting',typed:card?.typed||0,rows:card?.rows.length||0,rollNow:card?.sheet?.now||'',history:history.length,active,raf:!!raf,follow,wordFollow:card?.wordFollow??true,rollFollow:card?.rollFollow??true,held,hovered,inspecting:!!popup,followPlayback:settings.followPlayback,typingRate:TYPING_CPS*settings.typingSpeed,playbackFraction:playbackFraction(),visible:!!card&&!card.element.hidden,sharedBuild:BUILD};}};
  }

  var api = {BUILD: BUILD, DEFAULTS: DEFAULTS, TYPING_CPS: TYPING_CPS, FAMILY_COLORS: FAMILY_COLORS,
    createRenderer: createRenderer, typeCount: typeCount, mount: mount,
    stageOf: mvStageOf, reel: mvReel, decisionRow: mvDecisionRow, decisionRows: decisionRows,
    countedRow: countedRow, rejected: mvRrRejOf, verdicts: mvRrVerdicts,
    failed: mvRrFailed, matchRejected: mvRrMatchRej, rowKey: rowKey};
  root.PineSystem3MessageTile = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
}(typeof window !== 'undefined' ? window : globalThis));
