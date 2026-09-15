/* THE ORCHESTRATOR GLASS - what the conductor is actually doing, right now,
 * and the arithmetic behind every number he is working towards. (#1191)
 *
 * "I want to be able to access a pop-up that gives me advanced information
 *  about how the orchestrator is behaving in the background, showing me his
 *  real time behavior along with a avatar of glyphy in the top right corner,
 *  showing me him as a interactive element. I want to be able to expand each
 *  element with a triangle and basically see additional information about
 *  that element that the orchestrator is working towards. I want to see a
 *  task list in order of tasks that are actively being pursued by the
 *  orchestrator and how they're being handled. I want to see what supportive
 *  systems are being summoned and triggered by the orchestrator as he's
 *  using and managing tools in order to complete the task and dictate and
 *  guide and structure and manage the station."
 *
 * WHY THIS FILE COULD NOT BE WRITTEN UNTIL THE STATION WAS INSTRUMENTED.
 * An audit on 2026-09-15 established three things, and every one of them
 * stood between this screen and the words above:
 *
 *   - no loop on this station counted its own actions, and the process
 *     exposed no boot stamp, so "how many times has this keeper acted" was
 *     unanswerable for all SEVENTY-FIVE timer loops in app.py;
 *   - the orchestrator's narration of its own reasoning went to a 240-entry
 *     in-memory ring shared with the whole voice machine, which rotates in
 *     minutes and is written to no file;
 *   - and nothing anywhere recorded which supporting system a given piece of
 *     work summoned.
 *
 * So the telemetry was built first (#1191, app.py: orch_turn / orch_used /
 * orch_step and /api/orchestrator/glass) and this draws it. That matters for
 * reading this file: everything on this screen is a value the station
 * measured. Nothing here computes a number of its own, and nothing here is
 * decorative.
 *
 * THE BLIND SPOTS ARE ON THE FACE OF IT, NOT IN A COMMENT. Fifteen of the
 * seventy-five loops are stamped, plus four orchestration ticks, and
 * supporting systems are recorded at seven named doors. The panel prints
 * that, prints the groups it cannot see by name, and refuses to draw an
 * empty list as though it meant "the station is idle". This operator has
 * been bitten repeatedly by surfaces that implied sight they did not have -
 * "a check that can only print one answer is the artifact" - and a panel
 * that implies complete sight it does not have is worse than one that names
 * what it is missing.
 *
 * THE TRIANGLE. Every expandable element carries one: a Carbon caret that
 * rotates ninety degrees when it opens. The rows that carry a number the
 * orchestrator COMPUTED expand into the working - each input named, with its
 * own value - and any input sitting on its ceiling is marked AT ITS CAP,
 * because a factor pinned at its ceiling for 187 hours carries no
 * information and noticing that is the most useful thing on this screen.
 *
 * ES5 throughout, one IIFE, no dependencies beyond the three the page always
 * has (pineIcon, PineDuck, PineCorners) and every one of those is guarded.
 */
(function (root) {
  'use strict';

  var ID = 'pineOrchGlass';
  var PLACE = 'pineOrchGlassAt';
  var FOLDS = 'pineOrchGlassFolds';

  /* HOW OFTEN IT ASKS, AND WHY THAT NUMBER.
   *
   * Five seconds, and NOTHING AT ALL while it is shut.
   *
   * The reasoning is not "five feels live". It is that the register on the
   * server is the memory: orch_turn/orch_step keep a 240-deep tail of every
   * pass that DID something, so a turn that happened between two polls is
   * still on the next answer. The poll therefore only has to be often enough
   * to feel alive, not often enough to catch events - which is the trap
   * every faster surface on this station has fallen into.
   *
   * And this panel has been starved before by exactly that. On the tablet's
   * 400 kB/s link a 2.4 kB /api/orchestrator/asks was measured waiting 19 s
   * behind six permanently full HTTP/1.1 sockets, and a 650-byte
   * /api/radio/clock 21 s; that queue is what the operator feels as "the
   * popup is slow". So it is one route, one request, five seconds, and the
   * timer is cleared on close rather than left running against a hidden
   * box - a closed pop-up asks for nothing. */
  var EVERY_MS = 5000;

  /* The avatar's own clock. Six frames a second is enough for a blink and a
   * dot cycle and costs one small string build; it runs ONLY while the
   * pop-up is open and is cleared with it. */
  var FACE_MS = 160;

  var box = null;
  var timer = null;
  var faceTimer = null;
  var frame = 0;
  var last = null;              /* the newest payload, for repaint */
  var open = Object.create(null);  /* fold id -> true */
  var asks = 0;
  var lastMs = 0;
  var holding = false;
  var dragging = false;
  var sayAt = 0;                /* which of Glyphy's lines is showing */
  var pressed = false;          /* a pointer is down: do not repaint under it */

  /* ------------------------------------------------------------ plumbing */

  function where() {
    try {
      if (root.location && /^https?:$/.test(root.location.protocol)) return '';
      if (root.pineStationBase) return root.pineStationBase();
    } catch (err) { /* fall through to the desk's own door */ }
    return 'http://127.0.0.1:8096';
  }

  function key() {
    try { if (typeof root.SERVER_KEY === 'string') return root.SERVER_KEY; }
    catch (err) { /* not on this page */ }
    return '';
  }

  /* The desk is a file:// document and talks through the bridge; the tablet
   * is served by the station itself and a bare path is right. Same split
   * every view in this directory carries. */
  function get(path) {
    try {
      if (root.pineDesktop && root.pineDesktop.get) return root.pineDesktop.get(path);
    } catch (err) { /* fall through */ }
    var head = key() ? {Authorization: 'Bearer ' + key()} : {};
    return root.fetch(where() + path, {headers: head, cache: 'no-store'})
      .then(function (res) { return res.ok ? res.json() : null; });
  }

  function el(tag, cls, text) {
    var node = root.document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== null && typeof text !== 'undefined') node.textContent = String(text);
    return node;
  }

  /* NO EMOJI, EVER - Carbon or nothing, and guarded, because pine-icons.js
   * injects its sprite at load and a view built before it is there would
   * otherwise throw on every row. An icon that is missing costs a blank
   * span; it never costs the panel. */
  function icon(ref, label) {
    try {
      if (typeof root.pineIcon === 'function') return root.pineIcon(ref, label || '');
    } catch (err) { /* the text beside it still names the thing */ }
    return '';
  }

  function iconInto(node, ref, label) {
    var mark = icon(ref, label);
    if (!mark) return node;
    var slot = el('span', 'og-i');
    slot.innerHTML = mark;
    node.appendChild(slot);
    return node;
  }

  function num(value, dp) {
    var n = Number(value);
    if (!isFinite(n)) return '-';
    var places = typeof dp === 'number' ? dp : 0;
    var out = n.toFixed(places);
    /* Thousands separators, because "50920" and "5092" are the same shape
       at a glance and the whole point of this screen is noticing that one
       of them is absurd. */
    var bits = out.split('.');
    bits[0] = bits[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return bits.join('.');
  }

  function secs(value) {
    var n = Number(value);
    if (!isFinite(n)) return '-';
    if (n < 90) return num(n, 0) + 's';
    if (n < 5400) return num(n / 60, 1) + ' min';
    return num(n / 3600, 1) + ' h';
  }

  function ago(at) {
    var n = Number(at);
    if (!isFinite(n) || n <= 0) return '';
    var gap = (Date.now() / 1000) - n;
    if (gap < 0) gap = 0;
    if (gap < 60) return Math.round(gap) + 's ago';
    if (gap < 3600) return Math.round(gap / 60) + ' min ago';
    return (gap / 3600).toFixed(1) + ' h ago';
  }

  function clock(at) {
    var n = Number(at);
    if (!isFinite(n) || n <= 0) return '';
    var when = new Date(n * 1000);
    var hh = String(when.getHours());
    var mm = String(when.getMinutes());
    if (hh.length < 2) hh = '0' + hh;
    if (mm.length < 2) mm = '0' + mm;
    return hh + ':' + mm;
  }

  /* -------------------------------------------------------------- Glyphy
   *
   * His face is the same sprite the station panel draws (#980), lifted into
   * ES5 so the desk and the tablet can have it too - the desk renderer has
   * never had a Glyphy file at all. The MOOD IS NOT DECORATIVE and never
   * random: the server chooses it from the coordinator's own measurements
   * and says, in `why`, which measurement put him in it. A face that panics
   * at random is worse than no face; a face that panics when the air is
   * genuinely dead is the fastest way to know it from across the room. */
  var SPRITE = [
    '  \u2584\u2584\u2588\u2588\u2588\u2588\u2584\u2584  ',
    '\u2588\u2588        \u2588\u2588',
    '\u2588  {L}    {R}  \u2588',
    '\u2588     {N}     \u2588',
    '\u2588\u2588   {M}   \u2588\u2588',
    '  \u2580\u2580\u2588\u2588\u2588\u2588\u2580\u2580  '
  ];

  function look(mood, i) {
    var L = '\u25cf', R = '\u25cf', N = 'v', M = '___', tail = '';
    if (mood === 'pleased') { L = '^'; R = '^'; M = '\\_/'; }
    else if (mood === 'thinking') { tail = new Array(1 + (i % 4)).join('.') + '.'; }
    else if (mood === 'angry') { L = '\u2573'; R = '\u2573'; M = '\u2500\u2500\u2500'; }
    else if (mood === 'anxious') { M = '\u2500o\u2500'; if (i % 6 < 3) { N = '^'; } }
    else if (mood === 'rushing') { M = '\u2500\u2500\u2500'; if (i % 4 < 2) { L = 'o'; R = 'o'; } }
    else if (i % 26 === 12 || i % 26 === 13) { L = '\u2500'; R = '\u2500'; }
    return {L: L, R: R, N: N, M: M, tail: tail};
  }

  function faceRows(mood, i) {
    var o = look(mood, i);
    var out = [];
    for (var k = 0; k < SPRITE.length; k += 1) {
      out.push(SPRITE[k]
        .replace('{L}', o.L).replace('{R}', o.R)
        .replace('{N}', o.N).replace('{M}', (o.M + '   ').slice(0, 3)));
    }
    if (o.tail) out[2] = out[2] + ' ' + o.tail;
    return out.join('\n');
  }

  function paintFace() {
    if (!box) return;
    var pre = box.querySelector('.og-face');
    if (!pre) return;
    var mood = (last && last.face && last.face.mood) || 'watching';
    frame += 1;
    pre.textContent = faceRows(mood, frame);
  }

  /* WHAT MAKES HIM INTERACTIVE, since "an avatar" on its own is a picture.
   *
   * He is a real <button>. Pressing him steps through the three things the
   * server says about the conductor's state - what he is SAYING, WHY he is
   * in this mood (the measurement), and the coordinator's own BRIEF - and
   * pressing him again when there is nothing more to step to asks the
   * station for a fresh reading immediately instead of waiting out the poll.
   * Because he is a <button>, hot-corners' own _overControl already answers
   * true over him, so a press on his face can never be mistaken for a corner
   * gesture; nothing here reimplements that test. */
  function saying() {
    var face = (last && last.face) || {};
    var lines = [];
    if (face.say) lines.push({what: 'saying', text: String(face.say)});
    if (face.why) lines.push({what: 'because', text: String(face.why)});
    if (face.brief) lines.push({what: 'the brief', text: String(face.brief)});
    if (!lines.length) lines.push({what: 'saying', text: 'no reading yet'});
    if (sayAt >= lines.length) sayAt = 0;
    return lines[sayAt];
  }

  function paintSay() {
    if (!box) return;
    var line = saying();
    var what = box.querySelector('.og-say-what');
    var text = box.querySelector('.og-say-text');
    if (what) what.textContent = line.what;
    if (text) text.textContent = line.text;
  }

  function tapFace() {
    var face = (last && last.face) || {};
    var most = 0;
    if (face.say) most += 1;
    if (face.why) most += 1;
    if (face.brief) most += 1;
    sayAt += 1;
    if (sayAt >= Math.max(1, most)) { sayAt = 0; pull(); }
    paintSay();
  }

  /* ---------------------------------------------------------- the folds */

  /* A fold is a triangle, a title, an optional right-hand summary, and a
   * body that is BUILT ONLY WHEN IT IS OPEN. Two reasons that is lazy: the
   * arithmetic chain for sixteen roads is a lot of nodes to make every five
   * seconds for a panel nobody has opened, and a body that does not exist
   * cannot be the thing that throws and empties the rest of the pane - which
   * is how a single undeclared name once blanked five panes of the
   * presentation view at once, because they share one painter. */
  function fold(id, title, summary, build, cls) {
    var wrap = el('div', 'og-fold' + (cls ? ' ' + cls : ''));
    wrap.setAttribute('data-fold', id);
    var head = el('button', 'og-tri');
    head.setAttribute('type', 'button');
    head.setAttribute('aria-expanded', open[id] ? 'true' : 'false');
    iconInto(head, 'c:caret--right', '');
    head.appendChild(el('span', 'og-tri-title', title));
    if (summary) head.appendChild(el('span', 'og-tri-sum', summary));
    wrap.appendChild(head);
    var body = el('div', 'og-body');
    body.hidden = !open[id];
    wrap.appendChild(body);
    if (open[id]) {
      try { build(body); } catch (err) { body.appendChild(el('div', 'og-warn', 'this detail could not be drawn')); }
    }
    head.addEventListener('click', function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      if (open[id]) { delete open[id]; } else { open[id] = true; }
      wrap.classList.toggle('open', !!open[id]);
      head.setAttribute('aria-expanded', open[id] ? 'true' : 'false');
      body.hidden = !open[id];
      if (open[id] && !body.children.length) {
        try { build(body); } catch (err) { body.appendChild(el('div', 'og-warn', 'this detail could not be drawn')); }
      }
      remember();
      duck();
    });
    if (open[id]) wrap.classList.add('open');
    return wrap;
  }

  function remember() {
    var names = [];
    for (var k in open) if (open[k]) names.push(k);
    try { root.localStorage.setItem(FOLDS, JSON.stringify(names)); }
    catch (err) { /* a preference that will not save is not a fault */ }
  }

  function recall() {
    try {
      var saved = JSON.parse(root.localStorage.getItem(FOLDS) || '[]');
      for (var i = 0; i < saved.length; i += 1) open[String(saved[i])] = true;
    } catch (err) { open = Object.create(null); }
  }

  function anyOpen() {
    for (var k in open) if (open[k]) return true;
    return false;
  }

  /* ------------------------------------------------------------- the duck
   *
   * THE DECISION, AND THE MEASURED TRAP BEHIND IT.
   *
   * The standing rule is PineDuck.hold at 0.10 for anything diagnostic and
   * 0.02 for dictation, and this pop-up is diagnostic. But a hold here is
   * not free in the way it is on a report pad, for a reason measured on
   * 2026-09-15: listen.js reads PineDuck.reporting() to decide whether the
   * endless video wallpaper may be on screen at all, so ANY hold does not
   * merely lower the volume - it tears the wallpaper off the screen
   * entirely, for as long as the hold stands.
   *
   * That makes "hold for as long as the pop-up is open" the wrong shape.
   * This is a WATCHING surface, not a filing one: the operator may leave it
   * up for an hour while the show runs, and holding for that hour would
   * quiet the station he opened it to watch and blank his wallpaper the
   * whole time. Worse, it would be self-defeating - you cannot diagnose the
   * air you have muted.
   *
   * So the hold is tied to READING rather than to the window: the moment any
   * triangle is open the operator is reading arithmetic rather than
   * listening, and the broadcast goes to PineDuck.REPORT; the moment
   * everything is collapsed again it comes straight back. The hold carries
   * the pop-up's own element, so PineDuck's twice-a-second sweep gives the
   * sound back by itself if this surface is ever torn out without closing -
   * which a view change or a kiosk relaunch will do. */
  function duck() {
    var want = !!(box && anyOpen());
    if (want === holding) return;
    holding = want;
    try {
      if (!root.PineDuck) return;
      if (want) root.PineDuck.hold('orchestrator-glass', root.PineDuck.REPORT, box);
      else root.PineDuck.release('orchestrator-glass');
    } catch (err) { holding = false; }
  }

  /* ---------------------------------------------------------- the panes */

  function chip(text, cls) { return el('span', 'og-chip' + (cls ? ' ' + cls : ''), text); }

  function pair(body, name, value) {
    var line = el('div', 'og-pair');
    line.appendChild(el('span', 'og-pair-k', name));
    line.appendChild(el('span', 'og-pair-v', value));
    body.appendChild(line);
    return line;
  }

  /* ONE TURN. What the keeper was doing, in the order it did it, and what it
   * summoned while doing it. This is literally the operator's sentence -
   * "a task list in order of tasks that are actively being pursued... and
   * how they're being handled... what supportive systems are being summoned
   * and triggered". `steps` is the station's own narration, filed against
   * the pass that wrote it; `systems` is what that pass called. */
  function turnRow(row, n) {
    var id = 'turn:' + row.keeper + ':' + row.turn + ':' + n;
    var summary = (row.systems && row.systems.length)
      ? row.systems.length + ' system' + (row.systems.length === 1 ? '' : 's')
      : (row.steps && row.steps.length ? row.steps.length + ' line'
         + (row.steps.length === 1 ? '' : 's') : '');
    var title = row.keeper + (row.open ? '  (running)' : '');
    return fold(id, title, summary, function (body) {
      if (row.say) body.appendChild(el('div', 'og-lead', row.say));
      pair(body, 'pass', '#' + num(row.turn, 0));
      pair(body, 'began', clock(row.at) + '  ' + ago(row.at));
      if (row.ms) pair(body, 'took', row.ms + ' ms');
      if (row.steps && row.steps.length) {
        body.appendChild(el('div', 'og-sub', 'what it said while doing it'));
        for (var i = 0; i < row.steps.length; i += 1) {
          var step = row.steps[i] || {};
          var line = el('div', 'og-step');
          line.appendChild(chip(step.kind || '?', 'og-kind'));
          line.appendChild(el('span', 'og-step-text', step.text || ''));
          /* has_extra is the server's own flag for "there is paperwork
             behind this line" (#1107). It is shown rather than acted on:
             the extra lives on the pipeline ring, which this route does not
             carry, and inventing a way to fetch it would be inventing. */
          if (step.has_extra) line.appendChild(chip('has detail', 'og-more'));
          body.appendChild(line);
        }
      }
      if (row.systems && row.systems.length) {
        body.appendChild(el('div', 'og-sub', 'supporting systems it summoned'));
        for (var k = 0; k < row.systems.length; k += 1) {
          var got = row.systems[k] || {};
          var one = el('div', 'og-sys');
          iconInto(one, 'c:chart--network', '');
          one.appendChild(el('span', 'og-sys-name', got.system || ''));
          if (got.note) one.appendChild(chip(got.note, 'og-note'));
          if (got.calls > 1) one.appendChild(chip('x' + got.calls, 'og-count'));
          body.appendChild(one);
        }
      }
      if (!(row.steps && row.steps.length) && !(row.systems && row.systems.length)) {
        body.appendChild(el('div', 'og-quiet', 'this pass is recorded but said nothing and summoned nothing'));
      }
    }, row.open ? 'og-live' : '');
  }

  /* ONE LINK OF THE ARITHMETIC. The operator asked, of a want of 50,920
   * seconds for a thirty-minute book: "explain that in depth to me. What was
   * happening?" This is that explanation - the number it started from, the
   * factor, the number it became, the rule in words, every input by name
   * with its own value, and AT ITS CAP where the input is sitting on its
   * ceiling and has therefore stopped carrying information. */
  function chainLink(body, link) {
    var line = el('div', 'og-link' + (link.capped ? ' og-capped' : ''));
    var head = el('div', 'og-link-head');
    head.appendChild(el('span', 'og-link-name', link.name || ''));
    if (typeof link.factor !== 'undefined' && link.factor !== null) {
      head.appendChild(chip('x' + Number(link.factor).toFixed(2), 'og-factor'));
    }
    if (link.capped) {
      var flag = el('span', 'og-cap');
      iconInto(flag, 'c:warning--alt', '');
      flag.appendChild(el('span', null, 'AT ITS CAP'
        + (typeof link.cap !== 'undefined' ? ' (' + link.cap + ')' : '')));
      head.appendChild(flag);
    }
    line.appendChild(head);
    if (typeof link.was !== 'undefined' && link.was !== null) {
      line.appendChild(el('div', 'og-link-sum',
        secs(link.was) + '  ->  ' + secs(link.value)));
    } else {
      line.appendChild(el('div', 'og-link-sum', secs(link.value)));
    }
    if (link.rule) line.appendChild(el('div', 'og-rule', link.rule));
    var inputs = link.inputs || [];
    for (var i = 0; i < inputs.length; i += 1) {
      var got = inputs[i] || {};
      var value = got.value;
      if (typeof value === 'number') value = num(value, (value % 1) ? 2 : 0);
      else if (typeof value === 'boolean') value = value ? 'yes' : 'no';
      else value = String(value === null || typeof value === 'undefined' ? '' : value);
      if (got.unit) value += got.unit;
      var one = el('div', 'og-input');
      one.appendChild(el('span', 'og-input-k', got.name || ''));
      one.appendChild(el('span', 'og-input-v', value || '-'));
      line.appendChild(one);
    }
    body.appendChild(line);
  }

  /* ONE ROAD OF THE PLAN: what was ASKED and what was GRANTED side by side,
   * the working between them, and the sentence that refused the difference.
   * The refusal is the last thing in the fold on purpose - it is the end of
   * the chain, and reading it before the arithmetic makes it look arbitrary
   * when it is the only part of this that is not. */
  function roadRow(road, n) {
    var id = 'road:' + (road.road || n);
    var granted = road.granted || null;
    var refused = road.refused || null;
    var summary = secs(road.asked_seconds) + ' asked';
    if (granted && granted.items) summary += '  /  ' + granted.items + ' ordered';
    else if (refused) summary += '  /  refused';
    var pinned = false;
    var chain = road.chain || [];
    for (var c = 0; c < chain.length; c += 1) if (chain[c] && chain[c].capped) pinned = true;
    return fold(id, road.label || road.road || '', summary, function (body) {
      if (pinned) {
        var warn = el('div', 'og-warn');
        iconInto(warn, 'c:warning--alt', '');
        warn.appendChild(el('span', null,
          'a multiplier on this road is sitting on its ceiling. It has '
          + 'stopped carrying information and is only inflating the number.'));
        body.appendChild(warn);
      }
      if (road.why) body.appendChild(el('div', 'og-lead', road.why));

      body.appendChild(el('div', 'og-sub', 'how the number was reached'));
      if (!chain.length) {
        body.appendChild(el('div', 'og-quiet',
          'the working for this road was not recorded - the plan that made '
          + 'it predates this register, and it will carry the chain from '
          + 'the next half hour on'));
      }
      for (var i = 0; i < chain.length; i += 1) chainLink(body, chain[i] || {});

      body.appendChild(el('div', 'og-sub', 'asked against granted'));
      var table = el('div', 'og-two');
      var left = el('div', 'og-col');
      left.appendChild(el('div', 'og-col-h', 'asked'));
      left.appendChild(el('div', 'og-col-v', secs(road.asked_seconds)));
      if (refused && refused.wanted_items) {
        left.appendChild(el('div', 'og-col-s', num(refused.wanted_items, 0) + ' items'));
      }
      table.appendChild(left);
      var right = el('div', 'og-col');
      right.appendChild(el('div', 'og-col-h', 'granted'));
      right.appendChild(el('div', 'og-col-v',
        granted ? num(granted.items, 0) + ' item'
          + (Number(granted.items) === 1 ? '' : 's') : 'nothing'));
      if (granted && granted.room_seconds) {
        right.appendChild(el('div', 'og-col-s', secs(granted.room_seconds) + ' of room'));
      }
      table.appendChild(right);
      body.appendChild(table);

      var odds = (granted && granted.odds) || (refused && refused.odds);
      var each = (granted && granted.each_seconds) || (refused && refused.each_seconds);
      if (odds || each) {
        if (each) pair(body, 'room per finished item', secs(each));
        if (granted && granted.cost_seconds) pair(body, 'cost per attempt', secs(granted.cost_seconds));
        if (odds) pair(body, 'measured odds of finishing',
          (Number(odds) * 100).toFixed(1) + '%');
      }
      if (typeof road.due_in === 'number' && road.due_in < 1e8) {
        pair(body, 'next on the air in', secs(road.due_in));
      }
      if (road.bare) body.appendChild(chip('arrives bare', 'og-bad'));

      var learn = road.learning || {};
      if (learn.hours || learn.miss_streak) {
        body.appendChild(el('div', 'og-sub', 'what the closed hours say'));
        pair(body, 'closed hours', num(learn.hours, 0));
        pair(body, 'consecutive misses', num(learn.miss_streak, 0));
        pair(body, 'consecutive successes', num(learn.success_streak, 0));
        if (typeof learn.attainment_ema !== 'undefined') {
          pair(body, 'attainment (moving average)',
            (Number(learn.attainment_ema) * 100).toFixed(1) + '%');
        }
      }

      if (refused && refused.why) {
        body.appendChild(el('div', 'og-sub', 'and the sentence that refused the difference'));
        body.appendChild(el('div', 'og-refuse', refused.why));
      } else if (granted && granted.why) {
        body.appendChild(el('div', 'og-sub', 'why it was ordered'));
        body.appendChild(el('div', 'og-refuse', granted.why));
      }
    }, pinned ? 'og-pinned' : '');
  }

  function keeperRow(row, n) {
    var id = 'keeper:' + (row.name || n);
    var summary = num(row.turns, 0) + ' turn' + (Number(row.turns) === 1 ? '' : 's');
    return fold(id, row.name || '', summary, function (body) {
      if (row.say) body.appendChild(el('div', 'og-lead', row.say));
      /* THE COUNT IS THE POINT. Before #1191 nothing on this station could
         tell a keeper that has run four thousand times from one whose task
         died at boot and has run once. */
      pair(body, 'turns since boot', num(row.turns, 0));
      pair(body, 'passes that did something', num(row.acted, 0));
      pair(body, 'rate', num(row.per_minute, 2) + ' / min');
      if (row.quiet_for !== null && typeof row.quiet_for !== 'undefined') {
        pair(body, 'last woke', secs(row.quiet_for) + ' ago');
      }
      var systems = row.systems || [];
      if (systems.length) {
        body.appendChild(el('div', 'og-sub', 'what it leans on'));
        for (var i = 0; i < systems.length; i += 1) {
          var one = el('div', 'og-sys');
          iconInto(one, 'c:chart--network', '');
          one.appendChild(el('span', 'og-sys-name', systems[i].system));
          one.appendChild(chip('x' + systems[i].calls, 'og-count'));
          body.appendChild(one);
        }
      } else {
        body.appendChild(el('div', 'og-quiet',
          'this keeper has not summoned any of the seven recorded doors yet'));
      }
    });
  }

  /* --------------------------------------------------------- the drawing */

  function paint() {
    if (!box || !last) return;
    var main = box.querySelector('.og-main');
    if (!main) return;
    var scroll = main.scrollTop;
    main.innerHTML = '';

    var cover = (last.coverage || {});
    var live = last.live || [];
    var recent = last.recent || [];
    var roads = last.roads || [];
    var keepers = last.keepers || [];

    /* 1. WHAT HE IS PURSUING THIS INSTANT. An open pass with something in
       it. Empty is a normal and frequent state - most passes of most
       keepers wake, find nothing to do, and go back to sleep - so it says
       so in words rather than looking broken. */
    var nowFold = fold('now', 'being pursued right now',
      live.length ? String(live.length) : 'nothing open', function (body) {
        if (!live.length) {
          body.appendChild(el('div', 'og-quiet',
            'no instrumented keeper has a pass open with work in it at this '
            + 'instant. That is the usual state: most passes wake, find '
            + 'nothing to do and sleep again. The list below is what they '
            + 'did do.'));
          return;
        }
        for (var i = 0; i < live.length; i += 1) body.appendChild(turnRow(live[i], i));
      });
    main.appendChild(nowFold);

    /* 2. THE RUNNING ORDER - the tail, newest first. This is the list. */
    var span = '';
    if (last.oldest_at) span = 'back to ' + clock(last.oldest_at);
    main.appendChild(fold('order', 'what it has been doing, in order',
      recent.length ? recent.length + ' passes  ' + span : 'nothing yet',
      function (body) {
        if (!recent.length) {
          body.appendChild(el('div', 'og-quiet',
            'the register is empty. It starts empty at every restart - the '
            + 'station came up ' + secs(last.up_seconds) + ' ago.'));
          return;
        }
        for (var i = 0; i < recent.length; i += 1) body.appendChild(turnRow(recent[i], i));
      }));

    /* 3. WHAT IT IS WORKING TOWARDS, and the arithmetic behind each number. */
    main.appendChild(fold('roads', 'what it is asking the station for',
      roads.length ? roads.length + ' roads' : 'no plan yet', function (body) {
        if (last.plan_why) body.appendChild(el('div', 'og-lead', last.plan_why));
        if (!roads.length) {
          body.appendChild(el('div', 'og-quiet',
            'the coordinator has not written a work order since this '
            + 'process started. It writes one when the half hour closes.'));
          return;
        }
        for (var i = 0; i < roads.length; i += 1) body.appendChild(roadRow(roads[i], i));
      }));

    /* 4. THE KEEPERS AND THEIR COUNTS. */
    main.appendChild(fold('keepers', 'the keepers, and how often each has acted',
      keepers.length ? keepers.length + ' stamped' : 'none stamped yet',
      function (body) {
        body.appendChild(el('div', 'og-lead',
          'counted since this process started, ' + secs(last.up_seconds)
          + ' ago at ' + clock(last.boot_at) + '.'));
        for (var i = 0; i < keepers.length; i += 1) body.appendChild(keeperRow(keepers[i], i));
      }));

    /* 5. WHAT THIS PANEL CANNOT SEE. Last, always drawn, never collapsed
       away by default on a first run - because the failure this guards
       against is the operator reading an empty list as "nothing is
       happening" when the truth is "nothing here is measured". */
    main.appendChild(fold('blind', 'what this panel cannot see',
      (cover.loops_seen || 0) + ' of ' + (cover.loops_measured || 0) + ' loops',
      function (body) {
        var say = el('div', 'og-warn');
        iconInto(say, 'c:view', '');
        say.appendChild(el('span', null, cover.say || ''));
        body.appendChild(say);
        pair(body, 'kept on disk', cover.persisted ? 'yes' : 'no - memory only, lost at restart');
        pair(body, 'memory depth', num(last.tail_depth, 0) + ' of ' + num(last.tail_most, 0) + ' passes');
        pair(body, 'this panel has asked', asks + ' time' + (asks === 1 ? '' : 's')
          + (lastMs ? ', last took ' + lastMs + ' ms' : ''));
        pair(body, 'it asks every', (EVERY_MS / 1000) + 's while open, and nothing while shut');

        var doors = cover.doors || [];
        if (doors.length) {
          body.appendChild(el('div', 'og-sub',
            'a summoned system is recorded at these doors and nowhere else'));
          for (var d = 0; d < doors.length; d += 1) {
            var one = el('div', 'og-sys');
            iconInto(one, 'c:chart--network', '');
            one.appendChild(el('span', 'og-sys-name', doors[d].system));
            one.appendChild(el('span', 'og-note', doors[d].where));
            body.appendChild(one);
          }
        }
        var seen = cover.seen || [];
        if (seen.length) {
          body.appendChild(el('div', 'og-sub', 'what IS stamped'));
          for (var s = 0; s < seen.length; s += 1) {
            var row = el('div', 'og-blind');
            row.appendChild(el('span', 'og-blind-g', seen[s].name));
            row.appendChild(el('span', 'og-blind-n',
              seen[s].what + ' - ' + seen[s].when));
            body.appendChild(row);
          }
        }
        var blind = cover.blind || [];
        body.appendChild(el('div', 'og-sub',
          'and what is NOT - unmeasured, which is not the same as idle'));
        for (var b = 0; b < blind.length; b += 1) {
          var miss = el('div', 'og-blind');
          miss.appendChild(el('span', 'og-blind-g', blind[b].group));
          miss.appendChild(el('span', 'og-blind-n', blind[b].names));
          body.appendChild(miss);
        }
      }, 'og-blindfold'));

    main.scrollTop = scroll;
    paintSay();
    paintHeader();
  }

  function paintHeader() {
    if (!box || !last) return;
    var state = box.querySelector('.og-state');
    if (!state) return;
    state.innerHTML = '';
    var mood = (last.face && last.face.mood) || 'watching';
    state.appendChild(chip(mood, 'og-mood og-mood-' + mood));
    if (last.paused) state.appendChild(chip('paused', 'og-bad'));
    else if (!last.on) state.appendChild(chip('off air', 'og-bad'));
    var comm = last.commission || {};
    if (comm.mode) state.appendChild(chip('orders: ' + comm.mode, 'og-note'));
    box.setAttribute('data-mood', mood);
  }

  /* ----------------------------------------------------------- the fetch */

  function pull() {
    if (!box) return;                 /* a shut pop-up asks for nothing */
    var began = Date.now();
    asks += 1;
    get('/api/orchestrator/glass').then(function (got) {
      if (!box) return;               /* it closed while we were waiting */
      lastMs = Date.now() - began;
      if (!got) { trouble('the station did not answer'); return; }
      last = got;
      if (!pressed) paint();
    })['catch'](function () {
      if (!box) return;
      lastMs = Date.now() - began;
      trouble('the station could not be reached');
    });
  }

  function trouble(why) {
    if (!box) return;
    var state = box.querySelector('.og-state');
    if (!state) return;
    state.innerHTML = '';
    state.appendChild(chip(why, 'og-bad'));
  }

  /* --------------------------------------------------- the box and its drag */

  function place(node) {
    var left = 0, top = 0, w = 420, h = 540;
    try {
      var saved = JSON.parse(root.localStorage.getItem(PLACE) || 'null');
      if (saved) { left = saved.left; top = saved.top; w = saved.width || w; h = saved.height || h; }
    } catch (err) { saved = null; }
    if (!left && !top) {
      left = Math.max(80, (root.innerWidth || 1200) - w - 80);
      top = 80;
    }
    /* KEEP IT OFF THE HOT CORNERS. hot-corners owns a box in each corner of
       the window and a surface parked on one makes that gesture
       unreachable. cornerAt is ITS test, asked rather than reimplemented -
       if it says a corner of this box lands in a corner of the window, the
       box is nudged in until it does not. */
    var hops = 0;
    while (hops < 8 && cornerAt(left, top)) { left -= 24; top += 24; hops += 1; }
    if (left < 0) left = 0;
    if (top < 0) top = 0;
    node.style.left = left + 'px';
    node.style.top = top + 'px';
    node.style.width = w + 'px';
    node.style.height = h + 'px';
  }

  function cornerAt(x, y) {
    try {
      if (root.PineCorners && root.PineCorners._cornerAt) {
        return !!root.PineCorners._cornerAt(
          x, y, root.innerWidth || 0, root.innerHeight || 0);
      }
    } catch (err) { /* no hot corners on this surface */ }
    return false;
  }

  function overControl(node) {
    try {
      if (root.PineCorners && root.PineCorners._overControl) {
        return !!root.PineCorners._overControl(node);
      }
    } catch (err) { /* fall through */ }
    return false;
  }

  /* Mouse AND touch from one road: pointer events, which the desk's Electron
   * chrome and the tablet's WebView both have. The drag is refused when the
   * press lands on a control (hot-corners' own _overControl answers that)
   * and refused when it lands in a hot corner (its _cornerAt), so a corner
   * swipe that begins over this box still reaches the corner it was meant
   * for rather than dragging the box a few pixels and eating the gesture. */
  function drag(node, handle) {
    var from = null;
    handle.addEventListener('pointerdown', function (ev) {
      pressed = true;
      if (overControl(ev.target)) return;
      if (cornerAt(ev.clientX, ev.clientY)) return;
      from = {x: ev.clientX, y: ev.clientY,
              left: parseInt(node.style.left, 10) || 0,
              top: parseInt(node.style.top, 10) || 0};
      dragging = true;
      try { handle.setPointerCapture(ev.pointerId); } catch (err) { /* fine */ }
    });
    handle.addEventListener('pointermove', function (ev) {
      if (!from) return;
      node.style.left = (from.left + (ev.clientX - from.x)) + 'px';
      node.style.top = Math.max(0, from.top + (ev.clientY - from.y)) + 'px';
    });
    function done(ev) {
      pressed = false;
      if (!from) return;
      from = null;
      dragging = false;
      try { handle.releasePointerCapture(ev.pointerId); } catch (err) { /* fine */ }
      try {
        root.localStorage.setItem(PLACE, JSON.stringify({
          left: parseInt(node.style.left, 10) || 0,
          top: parseInt(node.style.top, 10) || 0,
          width: parseInt(node.style.width, 10) || 420,
          height: parseInt(node.style.height, 10) || 540}));
      } catch (err) { /* a position that will not save is not a fault */ }
      if (last) paint();
    }
    handle.addEventListener('pointerup', done);
    handle.addEventListener('pointercancel', done);
  }

  function build() {
    var node = el('div', 'og');
    node.id = ID;
    node.setAttribute('role', 'dialog');
    node.setAttribute('aria-label', 'the orchestrator');

    var head = el('div', 'og-head');
    var name = el('div', 'og-name');
    iconInto(name, 'c:bot', '');
    name.appendChild(el('span', null, 'The orchestrator'));
    head.appendChild(name);
    head.appendChild(el('div', 'og-state'));

    /* GLYPHY, TOP RIGHT, AND A REAL BUTTON. */
    var avatar = el('button', 'og-avatar');
    avatar.setAttribute('type', 'button');
    avatar.setAttribute('aria-label', 'Glyphy - press for what he is saying');
    var pre = el('pre', 'og-face', '');
    avatar.appendChild(pre);
    avatar.addEventListener('click', function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      tapFace();
    });
    head.appendChild(avatar);

    var shut = el('button', 'og-x');
    shut.setAttribute('type', 'button');
    shut.setAttribute('aria-label', 'Close');
    iconInto(shut, 'c:misuse', 'Close');
    shut.addEventListener('click', function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      close();
    });
    head.appendChild(shut);
    node.appendChild(head);

    var say = el('div', 'og-say');
    say.appendChild(el('span', 'og-say-what', 'saying'));
    say.appendChild(el('span', 'og-say-text', 'reading the board...'));
    node.appendChild(say);

    node.appendChild(el('div', 'og-main'));
    /* A SIBLING OF <main>, never a child of a view: every view in this
       window goes display:none the moment another tab is chosen, and three
       of them are webviews with documents of their own. A pop-up built
       inside one looks perfect in that view and does not exist in any
       other. */
    root.document.body.appendChild(node);
    drag(node, head);
    place(node);
    return node;
  }

  /* ------------------------------------------------------------- the door */

  function show() {
    if (box) return box;
    recall();
    box = build();
    frame = 0;
    sayAt = 0;
    paintFace();
    faceTimer = root.setInterval(paintFace, FACE_MS);
    pull();
    timer = root.setInterval(pull, EVERY_MS);
    duck();
    return box;
  }

  function close() {
    /* EVERY CLOCK STOPS AND THE SOUND COMES BACK. A pop-up that keeps a
       timer alive behind a removed node is a poll nobody can see and nobody
       can stop, which is exactly the shape of surface that has starved this
       panel before. */
    if (timer) { root.clearInterval(timer); timer = null; }
    if (faceTimer) { root.clearInterval(faceTimer); faceTimer = null; }
    try {
      if (holding && root.PineDuck) root.PineDuck.release('orchestrator-glass');
    } catch (err) { /* the sweep gives it back anyway */ }
    holding = false;
    if (box && box.parentNode) box.parentNode.removeChild(box);
    box = null;
    pressed = false;
  }

  function toggle() { if (box) { close(); return null; } return show(); }

  /* ------------------------------------------------------------- the way in
   *
   * The desk renderer has never had a Glyphy file at all, so there was
   * nothing to press. This is the same shape the station panel uses for him
   * (#980's glyphyDot): a small draggable face that sits out of the way,
   * remembers where it was put, and opens the glass when it is pressed.
   *
   * IT POLLS NOTHING. The dot's face is a fixed frame - no timer, no
   * request - because "a closed pop-up must ask for nothing at all" has to
   * include the thing that opens it. The face only starts moving, and the
   * station is only asked anything, once the glass is actually up. */
  var dotNode = null;
  var DOT_PLACE = 'pineOrchDotAt';
  var DOT_SHUT = 'pineOrchDotShut';

  function dot() {
    if (dotNode) return dotNode;
    try {
      if (root.localStorage.getItem(DOT_SHUT) === '1') return null;
    } catch (err) { /* no storage: show it */ }
    var node = el('button', 'og-dot');
    node.id = 'pineOrchDot';
    node.setAttribute('type', 'button');
    node.setAttribute('title', 'The orchestrator - what he is doing and why');
    node.setAttribute('aria-label', 'The orchestrator');
    var pre = el('pre', 'og-face', faceRows('watching', 0));
    node.appendChild(pre);
    var left = 0, top = 0;
    try {
      var saved = JSON.parse(root.localStorage.getItem(DOT_PLACE) || 'null');
      if (saved) { left = saved.left; top = saved.top; }
    } catch (err) { saved = null; }
    if (!left && !top) {
      left = Math.max(8, (root.innerWidth || 1200) - 150);
      top = Math.max(8, (root.innerHeight || 800) - 150);
    }
    /* Off the hot corners, using their own test rather than a guess. */
    var hops = 0;
    while (hops < 8 && cornerAt(left, top)) { left -= 24; top -= 24; hops += 1; }
    node.style.left = Math.max(0, left) + 'px';
    node.style.top = Math.max(0, top) + 'px';

    /* A press opens the glass; a DRAG does not, or the dot could never be
       moved without also opening what it opens. Four pixels of travel is
       the threshold, which is under a deliberate tap and over the wobble a
       thumb makes on the tablet. */
    var from = null;
    var moved = false;
    node.addEventListener('pointerdown', function (ev) {
      if (cornerAt(ev.clientX, ev.clientY)) return;
      moved = false;
      from = {x: ev.clientX, y: ev.clientY,
              left: parseInt(node.style.left, 10) || 0,
              top: parseInt(node.style.top, 10) || 0};
      try { node.setPointerCapture(ev.pointerId); } catch (err) { /* fine */ }
    });
    node.addEventListener('pointermove', function (ev) {
      if (!from) return;
      var dx = ev.clientX - from.x, dy = ev.clientY - from.y;
      if (!moved && (dx * dx + dy * dy) < 16) return;
      moved = true;
      node.style.left = Math.max(0, from.left + dx) + 'px';
      node.style.top = Math.max(0, from.top + dy) + 'px';
    });
    node.addEventListener('pointerup', function (ev) {
      if (!from) return;
      from = null;
      try { node.releasePointerCapture(ev.pointerId); } catch (err) { /* fine */ }
      if (!moved) { toggle(); return; }
      try {
        root.localStorage.setItem(DOT_PLACE, JSON.stringify({
          left: parseInt(node.style.left, 10) || 0,
          top: parseInt(node.style.top, 10) || 0}));
      } catch (err) { /* a position that will not save is not a fault */ }
    });
    /* And a way to put it away that does not need a preferences page. */
    node.addEventListener('contextmenu', function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      try { root.localStorage.setItem(DOT_SHUT, '1'); } catch (err) { /* fine */ }
      if (node.parentNode) node.parentNode.removeChild(node);
      dotNode = null;
    });
    root.document.body.appendChild(node);
    dotNode = node;
    return node;
  }

  function undot() {
    try { root.localStorage.removeItem(DOT_SHUT); } catch (err) { /* fine */ }
    return dot();
  }

  root.PineOrchGlass = {
    open: show,
    close: close,
    toggle: toggle,
    dot: dot,
    undot: undot,
    isOpen: function () { return !!box; },
    /* For the tests and for anything that wants to know how hard this
       surface is leaning on the station. */
    asks: function () { return asks; },
    /* The payload, as last received. Read-only by convention. */
    state: function () { return last; },
    EVERY_MS: EVERY_MS
  };
})(typeof window !== 'undefined' ? window : globalThis);
