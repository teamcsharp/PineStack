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
 * ----------------------------------------------------------------------
 * #1202, 2026-09-15: AND THE NETWORK'S OWN ACCOUNT.
 *
 * "I want the orchestrator page giving me the status of all of this on the
 *  network any time that I ask."
 *
 * Two more panes - the four rooms, and the made-against-heard - drawn from
 * two more keys on the same one route. They are written to read DEFENSIVELY,
 * and the long block beside them says exactly why and what that costs. The
 * one line worth carrying up here: NOTHING ON THIS SCREEN PRINTS A ZERO FOR
 * SOMETHING IT COULD NOT READ. A measured zero is drawn as 0 because it is a
 * measurement; an absent key says "could not be counted", which is the rule
 * the 3JS chooser already follows one file away, and it is the rule because
 * zero is the number that has misled this operator twice tonight.
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
  /* 2026-09-16 (#1220): HELD WHILE HE READS.
   *
   * `pressed` alone was never enough: it is true only while a pointer is
   * physically down, so it covers a drag and misses momentum scrolling, plain
   * reading, and a focused control - and paint() opens with innerHTML = '',
   * which destroys whatever had focus. That is what he felt as the cursor
   * moving. These stamp every sign of a person and hold the rebuild off. */
  var touchedAt = 0;            /* when a person last did anything in here */
  var waiting = false;          /* a payload arrived while he was reading */
  var READ_QUIET_MS = 12000;    /* how long he gets after his last touch */
  var restTimer = null;

  function touched() { touchedAt = Date.now(); }

  function reading() {
    if (pressed) return true;
    return (Date.now() - touchedAt) < READ_QUIET_MS;
  }

  /* Every road a person's attention arrives by. Passive where it can be, so
     watching for them can never itself make the list feel heavy. */
  function watchReading(node) {
    if (!node) return;
    var names = ['pointerdown', 'pointerup', 'wheel', 'scroll', 'touchstart',
                 'touchmove', 'keydown', 'focusin'];
    for (var i = 0; i < names.length; i += 1) {
      try {
        node.addEventListener(names[i], touched,
          names[i] === 'keydown' || names[i] === 'focusin'
            ? false : {passive: true, capture: true});
      } catch (err) { /* older host: the ones that took are enough */ }
    }
  }

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

  /* ================================================================ #1202
   *
   * THE NETWORK'S OWN ACCOUNT: THE FOUR ROOMS, AND MADE AGAINST HEARD.
   *
   * "I want the orchestrator page giving me the status of all of this on the
   *  network any time that I ask... how many messages were recorded, how many
   *  were played, how many sessions were added to the cover, how many were
   *  executed, how many covered sessions remain that are unused, and how many
   *  are scheduled... everything about how the orchestrator is handling the
   *  network when it comes to dealing with the four rooms and getting content
   *  out broadcasted. I want no wasted lines. It is nightmarish to hear of
   *  lines being recorded stored and never intended to be used or played."
   *
   * These two panes read `rooms` and `waste` off the same payload every other
   * pane here draws, on the same one route, at the same five seconds. No new
   * request, no second clock.
   *
   * WHY THEY ARE WRITTEN THIS WAY, which is not how the five panes above are
   * written. The server half of #1202 is deciding its own field names as it
   * goes, because what a "session" is and what "the cover" is on this station
   * is itself a question it has to answer. A panel written against a shape
   * that has not been decided yet has exactly two honest options: refuse to
   * draw until it is, or read whatever arrives and SAY what it read. This
   * does the second. Concretely, every row here:
   *
   *   - names a small set of keys it will accept, and when one of them is
   *     readable the fold says WHICH key carried the number. A name that
   *     changes on the server then shows up on the face of the panel instead
   *     of becoming a mystery number nobody can check;
   *   - and when NONE of them is readable the row is not drawn as a zero. It
   *     goes into a "could not be counted" list at the foot of its pane, BY
   *     THE NAMES IT LOOKED FOR, so the server agent can open this panel and
   *     read off what to send.
   *
   * Every key the station DID send that no row here claimed is drawn anyway,
   * under "what else the station sent". A field named something nobody here
   * guessed still reaches his eyes rather than being silently dropped - which
   * is the failure this whole screen exists to stop happening to work.
   *
   * THE ZERO RULE, AND WHY IT IS A RULE AND NOT A PREFERENCE. Zero has misled
   * this operator twice tonight: the 3JS chooser read "0 on this station" for
   * a station carrying thirty-two scenes, because it counted the wrong
   * window; and #1239's never-heard grace period read -1 as "exempt for
   * ever". Both were surfaces printing a confident number for something they
   * had not measured. So: a zero the station MEASURED is drawn as 0, because
   * a measured zero is information and hiding it would be the opposite fault.
   * An ABSENT key is never drawn as 0. told() below is the entirety of that
   * distinction - it answers null for missing, null, undefined, blank and
   * NaN, and answers 0 for a measured zero.
   * ==================================================================== */

  var UNREAD = 'could not be counted';

  /* MISSING IS NOT ZERO, AND A BOOLEAN IS NOT A COUNT. Number('') is 0,
   * Number([]) is 0 and Number(true) is 1 in this language, so each of those
   * would quietly become a number if this were one coercion. They are all
   * refused by name. */
  function told(value) {
    if (value === null || typeof value === 'undefined') return null;
    if (typeof value === 'number') return isFinite(value) ? value : null;
    if (typeof value === 'string') {
      if (!/\S/.test(value)) return null;
      var n = Number(value);
      return isFinite(n) ? n : null;
    }
    return null;
  }

  /* Try each accepted name in turn and report BOTH the value and the name
   * that carried it. The name is half the point: a panel that prints 412
   * without saying the station called it `never_heard_minutes` is a panel
   * nobody can check, and an unchecked number on this station has twice
   * turned out to be a different quantity than the label beside it. */
  function pick(src, names) {
    var i, got;
    if (!src || typeof src !== 'object') return {name: '', value: null};
    for (i = 0; i < names.length; i += 1) {
      got = told(src[names[i]]);
      if (got !== null) return {name: names[i], value: got};
    }
    return {name: '', value: null};
  }

  /* A DURATION MAY ARRIVE AS SECONDS OR AS MINUTES and the two differ by a
   * factor of sixty, which is exactly the size of error that makes a panel
   * lie with confidence. The unit is taken from the KEY NAME, never guessed
   * from the magnitude: a magnitude test would read 90 minutes of unheard
   * speech as 90 seconds and be wrong in the direction that UNDERSTATES the
   * waste, which on this screen is the one direction that must not happen. */
  function asSeconds(hit) {
    if (!hit || hit.value === null) return null;
    /* Anchored on a word boundary at BOTH ends, so `minutes` and
     * `never_heard_minutes` convert and a field that merely happens to end
     * in those three letters does not. */
    if (/(^|_)(minutes|mins|min)$/.test(hit.name)) return hit.value * 60;
    if (/(^|_)(hours|hrs)$/.test(hit.name)) return hit.value * 3600;
    return hit.value;
  }

  /* MINUTES, because that is the unit he used. Minutes of speech is what a
   * line costs to make and what a hole costs to fill - "render = 2.97 +
   * 1.05 x audio" - so minutes is the unit in which waste is comparable to
   * the work that made it. */
  function mins(seconds) {
    /* null and undefined are refused BEFORE the coercion, not after it:
     * Number(null) is 0 in this language, so a bare isFinite() guard would
     * turn "not measured" into "0.0 min" - the exact substitution this whole
     * block exists to prevent. Every caller already checks, and this checks
     * again, because the one that forgets is the one that ships. */
    if (seconds === null || typeof seconds === 'undefined') return UNREAD;
    var n = Number(seconds);
    if (!isFinite(n)) return UNREAD;
    return num(n / 60, 1) + ' min';
  }

  /* The server may send a list or a map and either is reasonable, so both are
   * accepted rather than one being declared correct. A map's key becomes the
   * row's name when the row does not carry one. */
  function named(obj, key) {
    var copy = {}, k;
    for (k in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, k)) copy[k] = obj[k];
    }
    if (!copy.name && !copy.label) copy.name = key;
    return copy;
  }

  function rowsOf(value) {
    var out = [], k, one, i;
    if (Array.isArray(value)) {
      for (i = 0; i < value.length; i += 1) {
        if (value[i] && typeof value[i] === 'object') out.push(value[i]);
      }
      return out;
    }
    if (value && typeof value === 'object') {
      for (k in value) {
        if (!Object.prototype.hasOwnProperty.call(value, k)) continue;
        one = value[k];
        if (one && typeof one === 'object' && !Array.isArray(one)) {
          out.push(named(one, k));
        } else if (told(one) !== null) {
          out.push({name: k, count: one});
        }
      }
    }
    return out;
  }

  function labelOf(row, fallback) {
    var names = ['label', 'name', 'room', 'title', 'key', 'kind', 'why'];
    for (var i = 0; i < names.length; i += 1) {
      if (row && typeof row[names[i]] === 'string' && /\S/.test(row[names[i]])) {
        return row[names[i]];
      }
    }
    return fallback;
  }

  function warnBox(sentence) {
    var warn = el('div', 'og-warn');
    iconInto(warn, 'c:warning--alt', '');
    warn.appendChild(el('span', null, sentence));
    return warn;
  }

  /* WHAT NOBODY HERE GUESSED. Printed rather than dropped: a number the
   * station went to the trouble of measuring must not become invisible
   * because this file was written an hour before the field was named. */
  function extras(body, src, used) {
    var k, value, rows = [], i;
    if (!src || typeof src !== 'object') return;
    for (k in src) {
      if (!Object.prototype.hasOwnProperty.call(src, k)) continue;
      if (used[k]) continue;
      value = src[k];
      if (value === null || typeof value === 'undefined') continue;
      if (typeof value === 'object') continue;   /* lists are drawn as rows */
      rows.push({k: k, v: value});
    }
    if (!rows.length) return;
    body.appendChild(el('div', 'og-sub', 'what else the station sent'));
    for (i = 0; i < rows.length; i += 1) {
      pair(body, rows[i].k, typeof rows[i].v === 'boolean'
        ? (rows[i].v ? 'yes' : 'no') : String(rows[i].v));
    }
  }

  /* AND WHAT IT DID NOT SEND - named, with the keys that were looked for.
   * "Could not be counted" on its own is a shrug, and this panel has never
   * shrugged: the blind pane has printed what it cannot see, by name, since
   * the day it was written, for exactly this reason. */
  function notCounted(body, missing) {
    var i, line;
    if (!missing.length) return;
    body.appendChild(el('div', 'og-sub', 'and what could NOT be counted'));
    body.appendChild(warnBox(missing.length
      + (missing.length === 1 ? ' of these is' : ' of these are')
      + ' not on this payload. They are NOT zero. A zero here would be the '
      + 'same lie the 3JS sheet told when it read "0 on this station" for a '
      + 'station carrying thirty-two scenes - a confident number for '
      + 'something nothing had measured.'));
    for (i = 0; i < missing.length; i += 1) {
      line = el('div', 'og-pair');
      line.appendChild(el('span', 'og-pair-k', missing[i].label));
      line.appendChild(el('span', 'og-pair-v', UNREAD));
      body.appendChild(line);
      body.appendChild(el('div', 'og-blind-n',
        'looked for: ' + missing[i].keys.join(', ')));
    }
  }

  /* ONE MEASURED ROW: a triangle, a name, a number that came from a
   * measurement rather than an estimate, and behind the triangle where that
   * measurement came from. Returns nothing; a row it could not read is
   * pushed onto `missing` instead of being drawn. */
  function tally(body, id, spec, src, used, missing) {
    var i, hit, shown, seconds = null;
    for (i = 0; i < spec.keys.length; i += 1) used[spec.keys[i]] = true;
    hit = pick(src, spec.keys);
    if (hit.value === null) { missing.push(spec); return; }
    if (spec.duration) {
      seconds = asSeconds(hit);
      shown = mins(seconds);
    } else {
      shown = num(hit.value, 0);
    }
    body.appendChild(fold(id, spec.label, shown, function (into) {
      if (spec.why) into.appendChild(el('div', 'og-lead', spec.why));
      pair(into, 'the measurement', shown);
      if (seconds !== null) {
        pair(into, 'in seconds', num(seconds, 0));
        pair(into, 'in hours', num(seconds / 3600, 2));
      }
      /* PROVENANCE. Everything on this screen is a value the station
         measured (#1191); this is which value, under the name the station
         itself gave it. */
      pair(into, 'the station called it', hit.name);
    }, spec.cls || ''));
  }

  /* ------------------------------------------------ made against heard */

  /* The keys each row will accept, most specific first. These are a READING
   * of the operator's own sentence, one row per clause of it, and the server
   * half is free to name things differently - a name that is not here shows
   * up under "what else the station sent" and the row that wanted it shows up
   * under "could not be counted", so nothing is lost either way. */
  var NEVER_SECS = ['never_heard_seconds', 'unheard_seconds', 'wasted_seconds',
    'never_heard_minutes', 'unheard_minutes', 'wasted_minutes'];
  var NEVER_COUNT = ['never_heard', 'unheard', 'never_played', 'wasted'];

  var WASTE_ROWS = [
    {id: 'recorded', label: 'messages recorded',
     keys: ['recorded', 'messages_recorded', 'lines_recorded', 'made'],
     why: 'every line this station rendered to audio and filed. This is the '
        + 'cost side of the account.'},
    {id: 'played', label: 'messages played',
     keys: ['played', 'messages_played', 'lines_played', 'heard'],
     why: 'of those, the ones that actually went out over the air. The gap '
        + 'between this and the row above is the whole subject of this pane.'},
    {id: 'covered', label: 'sessions added to the cover',
     keys: ['covered', 'added_to_cover', 'cover_added', 'sessions_covered'],
     why: 'work written into the cover for a later hour to draw on.'},
    {id: 'executed', label: 'sessions executed',
     keys: ['executed', 'cover_executed', 'sessions_executed'],
     why: 'covered work the running order actually reached and used.'},
    {id: 'unused', label: 'covered, still unused',
     keys: ['unused', 'covered_unused', 'cover_unused', 'cover_remaining'],
     why: 'sitting in the cover, not yet executed. This is not waste yet - '
        + 'it is the pile that BECOMES waste if the hour closes without it, '
        + 'and it is the number to watch rather than the number to total.'},
    {id: 'scheduled', label: 'scheduled',
     keys: ['scheduled', 'on_the_order', 'planned'],
     why: 'written into a running order with a slot to go out in. Work is '
        + 'only promised air by the running order - an event-fired road that '
        + 'never reaches it is prepared for nobody.'}
  ];

  var CLASS_LISTS = ['classes', 'unplayable', 'reasons', 'why_not', 'kinds'];

  /* The keys a class row consumes itself, so extras() can show anything the
     station sent beside them without repeating what is already drawn. */
  var CLASS_MARK = ['count', 'lines', 'items', 'messages', 'n', 'seconds',
    'duration_seconds', 'audio_seconds', 'minutes', 'mins', 'why', 'note',
    'name', 'label', 'room', 'title', 'key', 'kind'];

  function classRow(row, n) {
    var used = Object.create(null);
    var label = labelOf(row, 'class ' + (n + 1));
    var count = pick(row, ['count', 'lines', 'items', 'messages', 'n']);
    var secsHit = pick(row, ['seconds', 'duration_seconds', 'audio_seconds',
      'minutes', 'mins']);
    var held = asSeconds(secsHit);
    var summary = held !== null ? mins(held)
      : (count.value !== null ? num(count.value, 0) + ' lines' : UNREAD);
    var k;
    for (k = 0; k < CLASS_MARK.length; k += 1) used[CLASS_MARK[k]] = true;
    return fold('waste:class:' + label, label, summary, function (into) {
      if (typeof row.why === 'string' && row.why !== label) {
        into.appendChild(el('div', 'og-lead', row.why));
      } else if (typeof row.note === 'string') {
        into.appendChild(el('div', 'og-lead', row.note));
      }
      pair(into, 'lines', count.value === null ? UNREAD : num(count.value, 0));
      pair(into, 'minutes', held === null ? UNREAD : mins(held));
      if (count.name) pair(into, 'counted as', count.name);
      if (secsHit.name) pair(into, 'timed as', secsHit.name);
      extras(into, row, used);
    });
  }

  function buildWaste(body) {
    var src = last && last.waste;
    var used = Object.create(null);
    var missing = [];
    var i, hit, headSecs, headCount, classes, big, sub;

    if (!src || typeof src !== 'object') {
      body.appendChild(warnBox(
        'the made-against-heard account is not on this payload. That is NOT '
        + 'a station with nothing to account for - it is a station that has '
        + 'not been asked to count yet, and from here those two look '
        + 'identical, so this says which one it is rather than drawing '
        + 'zeroes over the difference.'));
      pair(body, 'the key this pane reads', 'waste');
      pair(body, 'what arrived instead', src === null ? 'null'
        : (typeof src === 'undefined' ? 'nothing' : typeof src));
      return;
    }

    /* THE HEADLINE IS THE ANSWER TO HIS SENTENCE, AND IT COMES FIRST.
     *
     * "It is nightmarish to hear of lines being recorded stored and never
     *  intended to be used or played."
     *
     * So this pane does not open with a total and work down to the waste.
     * It opens WITH the waste, in minutes, at the size of a headline, and
     * the totals sit underneath it. The 2026-09-14 ledger is why that
     * ordering is not decoration: 98% of everything this station "prepared"
     * was never heard, and that fact was reachable only by reading four
     * other numbers and subtracting. A number that has to be derived before
     * it can be felt is a number nobody reads. */
    for (i = 0; i < NEVER_SECS.length; i += 1) used[NEVER_SECS[i]] = true;
    for (i = 0; i < NEVER_COUNT.length; i += 1) used[NEVER_COUNT[i]] = true;
    hit = pick(src, NEVER_SECS);
    headSecs = asSeconds(hit);
    headCount = pick(src, NEVER_COUNT).value;

    big = el('div', 'og-big' + (headSecs ? ' og-big-bad' : ''));
    big.appendChild(el('div', 'og-big-h', 'made and never heard'));
    big.appendChild(el('div', 'og-big-v', headSecs === null ? UNREAD : mins(headSecs)));
    sub = el('div', 'og-big-s');
    if (headCount !== null) {
      sub.textContent = num(headCount, 0) + ' line'
        + (headCount === 1 ? '' : 's') + ' recorded and never played';
    } else {
      sub.textContent = 'the station did not send a count of the lines, only '
        + 'what is shown above';
    }
    big.appendChild(sub);
    if (hit.name) {
      big.appendChild(el('div', 'og-big-s', 'measured by the station as ' + hit.name));
    }
    body.appendChild(big);

    if (headSecs === null && headCount === null) {
      body.appendChild(warnBox(
        'this is the one number he asked for by name and it is not on the '
        + 'payload. It is not zero minutes - it is unmeasured. Looked for: '
        + NEVER_SECS.join(', ') + ', ' + NEVER_COUNT.join(', ') + '.'));
    }

    /* THE CLASSES. "40 minutes wasted" is a number to be upset about;
     * "31 minutes of it expired before its slot came round" is a number to
     * do something about. The breakdown is the actionable half. */
    for (i = 0; i < CLASS_LISTS.length; i += 1) used[CLASS_LISTS[i]] = true;
    classes = [];
    for (i = 0; i < CLASS_LISTS.length && !classes.length; i += 1) {
      classes = rowsOf(src[CLASS_LISTS[i]]);
    }
    body.appendChild(el('div', 'og-sub', 'why it was never heard'));
    if (classes.length) {
      for (i = 0; i < classes.length; i += 1) {
        body.appendChild(classRow(classes[i], i));
      }
    } else {
      body.appendChild(el('div', 'og-quiet',
        'the station did not break the unheard work into classes on this '
        + 'payload, so this pane can say how much went unheard but not WHY '
        + 'any of it did. Looked for: ' + CLASS_LISTS.join(', ') + '.'));
    }

    /* AND THEN the totals, underneath, where he asked for them to be. */
    body.appendChild(el('div', 'og-sub', 'the account, clause by clause'));
    for (i = 0; i < WASTE_ROWS.length; i += 1) {
      tally(body, 'waste:' + WASTE_ROWS[i].id, WASTE_ROWS[i], src, used, missing);
    }

    extras(body, src, used);
    notCounted(body, missing);
  }

  function wastePane() {
    var src = last && last.waste;
    var summary, headSecs, headCount, loud;
    if (!src || typeof src !== 'object') {
      summary = UNREAD;
      loud = 'og-blindfold';
    } else {
      headSecs = asSeconds(pick(src, NEVER_SECS));
      headCount = pick(src, NEVER_COUNT).value;
      if (headSecs !== null) summary = mins(headSecs) + ' never heard';
      else if (headCount !== null) summary = num(headCount, 0) + ' never heard';
      else summary = UNREAD;
      loud = (headSecs > 0 || headCount > 0) ? 'og-pinned' : '';
    }
    return fold('waste', 'made and never heard', summary, buildWaste, loud);
  }

  /* ------------------------------------------------ #1204 the box itself */

  /* THE PRESSURE PANE, AND THE OFFER.
   *
   * "I want to find out what happened, prevent it, and also offer dialogue
   *  to prevent that sort of issue from happening by offering to basically
   *  relieve the pressure if this sort of situation comes up."
   *
   * WHAT HAPPENED, MEASURED. The DGX Spark this station runs on froze at
   * 09:50:14 on 2026-09-15, 35 hours up, no shutdown sequence at all - the
   * journal stops mid-sentence and it had to be power-cycled. The machine
   * had been warning for fourteen hours, and the only place it warned was
   * a text file on the host that nobody reads until after a freeze. The
   * last thing it ever wrote:
   *
   *   2026-09-15 08:22:03 avail=16.7G tier1: ComfyUI cache freed
   *
   * 16.7G is below the valve's own tier2 threshold of 18, and tier2 said
   * NOTHING - its only move was to unload an idle voice engine, and at
   * 08:22 this station renders all of its dialogue in real time, so nothing
   * was idle. Worse, the kernel had logged NINETEEN NVRM NV_ERR_NO_MEMORY
   * failures in that boot - GPU driver allocations failing - eight of them
   * in the last two and a half hours, while the valve watched CPU-side
   * MemAvailable, which never fell below 12G.
   *
   * WHY IT IS THE SECOND PANE. The panes on this screen are a claim about
   * what matters. Everything below this one - every road, every keeper,
   * every hour of prepared air - is arithmetic performed by a process on a
   * box, and when the box stops, all of it stops at once with no warning
   * and no recording. Only "what is happening THIS INSTANT" outranks it.
   *
   * IT COSTS THE STATION NOTHING TO DRAW. There is no second route and no
   * second poll: the reading rides the same /api/orchestrator/glass payload
   * every other pane here rides, and on the server it is composed out of
   * the resource guard's own 45-second in-memory snapshot. This panel polls
   * every five seconds and this station goes deaf when its event loop
   * stalls, so a pane about the machine freezing must not be able to help
   * it freeze.
   *
   * AND IT NEVER PRINTS A ZERO IT DID NOT MEASURE. A director that is not
   * answering, a director too old to know about the GPU, and a director
   * that could not read the kernel log are three different sentences. The
   * station composes all of them; this file draws what it is handed and
   * invents nothing, which is the rule the #1202 panes above already keep.
   *
   * THE OFFER IS AN OFFER. Nothing here acts on its own initiative, and
   * nothing here can act at all until a person presses twice: the first
   * press arms the button and shows what the rung COSTS, the second sends
   * it, and six seconds of not pressing disarms it. Declining is simply not
   * pressing a second time. The station is never given the initiative to
   * evict anything beyond the ladder the host already had. */

  var OFFERS_ARMED = 0;         /* tier armed and awaiting a second press */
  var OFFERS_BUSY = 0;          /* tier currently in flight */
  var OFFERS_SAID = null;       /* what the host said about the last press */
  var OFFERS_TIMER = 0;

  /* The only POST this panel makes. get() above is the read road and is
     used by the five-second poll; this is reached only by a human pressing
     a button twice, which is why a write door is acceptable on a surface
     whose whole rule is that a panel read may never become a station
     action. */
  function post(path) {
    try {
      if (root.pineDesktop && root.pineDesktop.post) return root.pineDesktop.post(path, {});
    } catch (err) { /* fall through to the bare door */ }
    var head = key() ? {Authorization: 'Bearer ' + key()} : {};
    return root.fetch(where() + path, {method: 'POST', headers: head, cache: 'no-store'})
      .then(function (res) { return res.ok ? res.json() : null; });
  }

  function disarm() {
    OFFERS_ARMED = 0;
    if (OFFERS_TIMER) { try { root.clearTimeout(OFFERS_TIMER); } catch (err) { /* already gone */ } }
    OFFERS_TIMER = 0;
  }

  function askRelieve(tier) {
    disarm();
    OFFERS_BUSY = tier;
    OFFERS_SAID = null;
    paint();
    post('/api/orchestrator/pressure/relieve?tier=' + tier).then(function (got) {
      OFFERS_BUSY = 0;
      OFFERS_SAID = (got && got.say)
        ? {say: String(got.say), lines: (got && got.said) || [], ok: !!(got && got.ok)}
        : {say: 'the station did not answer the request', lines: [], ok: false};
      paint();
    })['catch'](function () {
      OFFERS_BUSY = 0;
      OFFERS_SAID = {say: 'the station could not be reached', lines: [], ok: false};
      paint();
    });
  }

  function offerButton(body, offer) {
    var tier = Number(offer && offer.tier) || 0;
    if (!tier) return;
    var ready = !(offer && offer.ready === false);
    var row = el('div', 'og-offer' + (ready ? '' : ' og-offer-cold'));
    var btn = el('button', 'og-offer-b');
    btn.setAttribute('type', 'button');
    if (OFFERS_BUSY === tier) {
      btn.textContent = 'asking the host...';
      btn.disabled = true;
    } else if (OFFERS_ARMED === tier) {
      btn.className = 'og-offer-b og-offer-armed';
      iconInto(btn, 'c:warning--alt', '');
      btn.appendChild(el('span', null, 'press again to confirm'));
    } else {
      iconInto(btn, 'c:renew', '');
      btn.appendChild(el('span', null, 'tier ' + tier + ' - '
        + String((offer && offer.label) || 'relieve pressure')));
      if (OFFERS_BUSY) btn.disabled = true;
    }
    btn.addEventListener('click', function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      if (OFFERS_BUSY) return;
      if (OFFERS_ARMED === tier) { askRelieve(tier); return; }
      disarm();
      OFFERS_ARMED = tier;
      try {
        OFFERS_TIMER = root.setTimeout(function () { disarm(); paint(); }, 6000);
      } catch (err) { OFFERS_TIMER = 0; }
      paint();
    });
    row.appendChild(btn);
    /* THE PRICE, ALWAYS BESIDE THE BUTTON. An offer whose cost is hidden
       until after it is taken is not an offer. */
    row.appendChild(el('div', 'og-offer-cost',
      String((offer && offer.costs) || 'the host did not say what this costs')));
    if (!ready) {
      row.appendChild(el('div', 'og-offer-cost',
        'the host says there is nothing here to take right now.'));
    }
    body.appendChild(row);
  }

  function buildPressure(body) {
    var src = (last && last.pressure) || null;
    var i, j, k, n, one, recent, offers, lines;
    if (!src || typeof src !== 'object') {
      body.appendChild(el('div', 'og-quiet',
        'this station is not sending a reading of the box it runs on. That '
        + 'is a blind spot, not a clean bill of health: the machine froze '
        + 'once on 2026-09-15 with every server number still green.'));
      return;
    }
    if (src.readable === false) {
      body.appendChild(warnBox(String(src.say || UNREAD)));
      return;
    }
    body.appendChild(el('div', 'og-quiet', String(src.say || UNREAD)));

    /* THE NUMBERS, UNDERNEATH THE WORDS. told() is the #1202 rule - an
       absent key says so rather than drawing a zero. */
    pair(body, 'memory free', told(src.avail_gb) === UNREAD
      ? UNREAD : num(src.avail_gb, 1) + 'G');
    pair(body, 'pressure tier', told(src.tier));
    n = (src.nvrm && typeof src.nvrm === 'object') ? src.nvrm : null;
    if (!n) {
      pair(body, 'GPU allocation failures', UNREAD);
    } else if (n.readable === true) {
      pair(body, 'GPU failures, last 10 min', told(n.in_10m));
      pair(body, 'GPU failures, last hour', told(n.in_1h));
      pair(body, 'last GPU failure', (n.last_seconds === null
        || typeof n.last_seconds === 'undefined')
        ? 'none in the window' : mins(n.last_seconds) + ' ago');
    } else if (n.readable === false) {
      body.appendChild(warnBox('the host could not read its own kernel log ('
        + String(n.why || 'no reason given') + '), so GPU allocation '
        + 'failures are invisible. That is the signal that preceded the '
        + '2026-09-15 freeze by fourteen hours.'));
    } else {
      pair(body, 'GPU allocation failures', 'not scanned yet');
    }
    if (told(src.heard_seconds) !== UNREAD) {
      pair(body, 'this reading is', mins(src.heard_seconds) + ' old');
    }

    /* WHAT THE VALVE ITSELF LAST SAID. Its log used to be the only trace
       of any of this, and it lived on the host where nobody reads it. */
    recent = rowsOf(src.recent);
    if (recent.length) {
      body.appendChild(el('div', 'og-sub', 'what the valve last did'));
      for (i = 0; i < recent.length; i += 1) {
        one = recent[i] || {};
        body.appendChild(el('div', 'og-valve-line',
          (one.at ? clock(one.at) + '  ' : '') + String(one.what || '')));
      }
    }

    /* THE OFFER. */
    offers = rowsOf(src.offers);
    if (!offers.length) {
      body.appendChild(el('div', 'og-quiet',
        'the host is not offering anything right now.'));
    } else {
      body.appendChild(el('div', 'og-sub',
        'relieve it now, rather than waiting for a threshold'));
      for (j = 0; j < offers.length; j += 1) offerButton(body, offers[j]);
    }
    if (OFFERS_SAID) {
      body.appendChild(el('div', 'og-sub', 'what the host did'));
      body.appendChild(el('div', 'og-quiet', OFFERS_SAID.say));
      lines = OFFERS_SAID.lines || [];
      for (k = 0; k < lines.length; k += 1) {
        body.appendChild(el('div', 'og-valve-line', String(lines[k])));
      }
    }
  }

  function pressurePane() {
    var src = (last && last.pressure) || null;
    var summary, loud = '', tier, n;
    if (!src || typeof src !== 'object') {
      summary = UNREAD;
      loud = 'og-blindfold';
    } else if (src.readable === false) {
      summary = 'the host is not answering';
      loud = 'og-blindfold';
    } else {
      tier = Number(src.tier) || 0;
      summary = (told(src.avail_gb) === UNREAD)
        ? UNREAD : num(src.avail_gb, 1) + 'G free';
      n = (src.nvrm && typeof src.nvrm === 'object') ? src.nvrm : null;
      if (n && n.readable === true && Number(n.in_1h) > 0) {
        summary += ',  ' + num(n.in_1h, 0) + ' GPU failure'
          + (Number(n.in_1h) === 1 ? '' : 's') + '/h';
      }
      if (tier > 0) { summary += ',  tier ' + tier; loud = 'og-pinned'; }
      if (n && n.readable === false) loud = 'og-blindfold';
    }
    return fold('pressure', 'the box this station runs on', summary,
      buildPressure, loud);
  }

  /* ---------------------------------------------------- the four rooms */

  var ROOM_ROWS = [
    {id: 'in', label: 'went in',
     keys: ['in', 'went_in', 'arrived', 'entered', 'input', 'queued', 'taken'],
     why: 'what this room was handed.'},
    {id: 'out', label: 'came out',
     keys: ['out', 'came_out', 'left', 'output', 'done', 'completed', 'passed'],
     why: 'what it handed on. The difference between this and the row above '
        + 'is work that went in and has not come out.'},
    {id: 'stuck', label: 'stuck here now',
     keys: ['stuck', 'waiting', 'held', 'backlog', 'pending', 'blocked'],
     why: 'sitting in this room right now, neither finished nor refused.'}
  ];
  var ROOM_HELD = ['stuck_for', 'stuck_seconds', 'oldest_seconds',
    'waiting_seconds', 'oldest_age', 'stuck_minutes', 'oldest_minutes'];

  function roomRow(row, n) {
    var label = labelOf(row, 'room ' + (n + 1));
    var used = Object.create(null);
    var missing = [];
    var went = pick(row, ROOM_ROWS[0].keys);
    var came = pick(row, ROOM_ROWS[1].keys);
    var stuck = pick(row, ROOM_ROWS[2].keys);
    var heldHit = pick(row, ROOM_HELD);
    var held = asSeconds(heldHit);
    var summary, i;

    if (went.value === null && came.value === null && stuck.value === null) {
      summary = UNREAD;
    } else {
      summary = (went.value === null ? '-' : num(went.value, 0)) + ' in  /  '
        + (came.value === null ? '-' : num(came.value, 0)) + ' out';
      if (stuck.value) summary += '  /  ' + num(stuck.value, 0) + ' stuck';
    }

    for (i = 0; i < ROOM_HELD.length; i += 1) used[ROOM_HELD[i]] = true;
    used.label = true; used.name = true; used.room = true;
    used.title = true; used.key = true; used.kind = true; used.why = true;

    return fold('room:' + label, label, summary, function (into) {
      /* WHAT IS STUCK AND FOR HOW LONG is the operator's own third clause
         and the only one that names a fault rather than a count. It is
         drawn first, loudly, when there is one - a room holding work is the
         thing between a recorded line and a heard one. */
      if (stuck.value && held !== null) {
        into.appendChild(warnBox(num(stuck.value, 0) + ' piece'
          + (stuck.value === 1 ? '' : 's') + ' of work stuck in ' + label
          + ', the oldest for ' + secs(held) + '. Work that sits here is '
          + 'work that was made and is not being heard.'));
      } else if (stuck.value) {
        into.appendChild(warnBox(num(stuck.value, 0) + ' piece'
          + (stuck.value === 1 ? '' : 's') + ' of work stuck in ' + label
          + '. How long it has been stuck was not measured - the station '
          + 'sent a count without an age. Looked for: '
          + ROOM_HELD.join(', ') + '.'));
      }
      if (typeof row.why === 'string' && row.why !== label) {
        into.appendChild(el('div', 'og-lead', row.why));
      }

      for (i = 0; i < ROOM_ROWS.length; i += 1) {
        tally(into, 'room:' + label + ':' + ROOM_ROWS[i].id,
          ROOM_ROWS[i], row, used, missing);
      }

      /* THE CARRY. Both numbers measured, so the subtraction is measured
         too - it is not an estimate and it is not a second source. */
      if (went.value !== null && came.value !== null) {
        pair(into, 'went in and has not come out',
          num(went.value - came.value, 0));
      }
      if (held !== null) {
        pair(into, 'the oldest thing here has waited', secs(held));
        pair(into, 'the station timed it as', heldHit.name);
      }

      extras(into, row, used);
      notCounted(into, missing);
    }, stuck.value ? 'og-pinned' : '');
  }

  function buildRooms(body) {
    var src = last && last.rooms;
    var rows = rowsOf(src);
    var i;
    if (!src || typeof src !== 'object') {
      body.appendChild(warnBox(
        'the room flow is not on this payload. The rooms are not empty - '
        + 'they are uncounted, and drawing an empty list here would read as '
        + '"nothing is moving" when the truth is "nothing here is measured". '
        + 'That is the exact failure the blind pane below was written to '
        + 'stop, and it applies to this pane too.'));
      pair(body, 'the key this pane reads', 'rooms');
      pair(body, 'what arrived instead', src === null ? 'null'
        : (typeof src === 'undefined' ? 'nothing' : typeof src));
      return;
    }
    if (!rows.length) {
      body.appendChild(el('div', 'og-quiet',
        'the station sent a rooms ledger with no rooms in it. That is an '
        + 'answer, not an absence - but it is not the four rooms either, so '
        + 'it is worth saying out loud.'));
      return;
    }
    body.appendChild(el('div', 'og-lead',
      'what went in, what came out, and what is stuck - per room, counted '
      + 'since this process started ' + secs(last.up_seconds) + ' ago.'));
    for (i = 0; i < rows.length; i += 1) body.appendChild(roomRow(rows[i], i));
  }

  function roomsPane() {
    var src = last && last.rooms;
    var rows = rowsOf(src);
    var summary, stuckTotal = null, i, one, loud = '';
    if (!src || typeof src !== 'object') {
      summary = UNREAD;
      loud = 'og-blindfold';
    } else {
      for (i = 0; i < rows.length; i += 1) {
        one = pick(rows[i], ROOM_ROWS[2].keys);
        if (one.value !== null) stuckTotal = (stuckTotal || 0) + one.value;
      }
      summary = rows.length + ' room' + (rows.length === 1 ? '' : 's');
      if (stuckTotal) {
        summary += ',  ' + num(stuckTotal, 0) + ' stuck';
        loud = 'og-pinned';
      }
    }
    return fold('rooms', 'the four rooms, and what is moving through them',
      summary, buildRooms, loud);
  }

  /* --------------------------------------------------------- the drawing */

  function paint() {
    if (!box || !last) return;
    var main = box.querySelector('.og-main');
    if (!main) return;
    var scroll = main.scrollTop;
    /* #1220: innerHTML = '' destroys whatever had focus, which he reported as
       the cursor moving. Remember it by id so it can be handed back. */
    var hadFocus = '';
    try {
      var act = root.document.activeElement;
      if (act && act.id && main.contains(act)) hadFocus = act.id;
    } catch (err) { hadFocus = ''; }
    waiting = false;
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

    /* #1204 - THE BOX ITSELF, SECOND. It froze on 2026-09-15 at 09:50:14
       with every server number on this panel still green, and took the
       whole station with it. Everything below this pane is arithmetic
       performed by a process on that box. */
    main.appendChild(pressurePane());

    /* 2 and 3. #1202 - THE ACCOUNT, AND IT IS SECOND, NOT SIXTH.
     *
     * "I want no wasted lines. It is nightmarish to hear of lines being
     *  recorded stored and never intended to be used or played."
     *
     * The order of the panes on this screen is a claim about what matters,
     * and putting the waste ledger below four folds of arithmetic would be
     * the claim that it matters less than the arithmetic. It does not. The
     * only thing above it is what is happening THIS INSTANT, which is the
     * one thing that can change while he is reading.
     *
     * Waste before rooms, because the rooms explain the waste: he asked
     * about the four rooms in the same breath as "getting content out
     * broadcasted", so the room flow is the mechanism and the account is the
     * result, and a person reads the result first and then asks why.
     *
     * NEITHER PANE IS SKIPPED WHEN ITS KEY IS ABSENT. A pane that vanishes
     * when the station stops sending it reads, from the operator's chair, as
     * "there is nothing to see" - which is the same fault as a zero wearing a
     * different coat. It draws, its summary says "could not be counted", and
     * its body says which key was missing. */
    main.appendChild(wastePane());
    main.appendChild(roomsPane());

    /* 4. THE RUNNING ORDER - the tail, newest first. This is the list. */
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

    /* 5. WHAT IT IS WORKING TOWARDS, and the arithmetic behind each number. */
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

    /* 6. THE KEEPERS AND THEIR COUNTS. */
    /* 2026-09-21 (#1226): SEGMENTS1226 - THE PLACE TO WORK, not to read.
     *
     * "I want a section for segments and I want to expand it and be able to
     *  see every segment that's being scheduled... click on it and modify the
     *  system prompts and add different system prompts and try different
     *  system prompts for each section."
     *
     * Drawn by pine-segments.js, which owns the prompt shelves, the topic
     * bank and the dropped-story window. It is placed here, below what the
     * orchestrator is DOING, because the order of these panes is a claim
     * about what matters and a workbench should not stand in front of the
     * instruments. */
    main.appendChild(fold('segments',
      'the segments, and the words behind them',
      'prompts, topics, stories', function (body) {
        if (root.PineSegments && typeof root.PineSegments.pane === 'function') {
          root.PineSegments.pane(body);
          return;
        }
        body.appendChild(el('div', 'og-quiet',
          'the segments view is not loaded on this terminal. On the tablet it '
          + 'arrives with the app; on the desk it is a renderer file.'));
      }));

    main.appendChild(fold('keepers', 'the keepers, and how often each has acted',
      keepers.length ? keepers.length + ' stamped' : 'none stamped yet',
      function (body) {
        body.appendChild(el('div', 'og-lead',
          'counted since this process started, ' + secs(last.up_seconds)
          + ' ago at ' + clock(last.boot_at) + '.'));
        for (var i = 0; i < keepers.length; i += 1) body.appendChild(keeperRow(keepers[i], i));
      }));

    /* 7. WHAT THIS PANEL CANNOT SEE. Last, always drawn, never collapsed
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

        /* #1202: THE TWO NEW LEDGERS ARE ACCOUNTED FOR HERE TOO, because
           this pane is the one the operator is meant to trust about what is
           NOT known, and two panes that can quietly go blank belong on it. */
        pair(body, 'the four rooms ledger',
          (last.rooms && typeof last.rooms === 'object')
            ? 'sent by this build'
            : 'NOT on this payload - the room flow is unmeasured, not empty');
        pair(body, 'the made-against-heard ledger',
          (last.waste && typeof last.waste === 'object')
            ? 'sent by this build'
            : 'NOT on this payload - the waste account is unmeasured, not zero');

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
    /* #1220: ...and again after layout. Assigning scrollTop immediately after
       innerHTML='' is CLAMPED to whatever height the box has at that instant,
       so a restore to 900px can land at 200 and stay there. One frame later
       the content is measured and the same assignment takes. */
    try {
      root.requestAnimationFrame(function () {
        if (!box || !main || !main.isConnected) return;
        if (Math.abs(main.scrollTop - scroll) > 2) main.scrollTop = scroll;
        if (!hadFocus) return;
        var back = main.querySelector('#' + hadFocus);
        if (back && back.focus) { try { back.focus({preventScroll: true}); } catch (err) { back.focus(); } }
      });
    } catch (err) { /* no rAF: the assignment above is what there is */ }
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
      /* #1220: the data is fresh either way; the BODY waits until he is
         done. The face and header still move - one line each, and neither
         touches his place in the list. */
      if (reading()) { waiting = true; paintSay(); paintHeader(); }
      else { paint(); }
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
    /* #1226: a markdown dropped ANYWHERE on this window becomes a plotline.
       Registered on the whole box rather than on the fold, because he
       described dropping it "onto the orchestrator" - not onto a strip of
       it he has to find first. */
    try {
      if (root.PineSegments && root.PineSegments.acceptDrops) {
        root.PineSegments.acceptDrops(node);
      }
    } catch (err) { /* a window that cannot take a drop is still a window */ }
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
    /* #1220: he stopped reading - catch the view up, once. Checked often
       enough to feel prompt and doing nothing at all unless something is
       actually waiting. */
    restTimer = root.setInterval(function () {
      if (!box || !waiting || reading()) return;
      paint();
    }, 1000);
    touchedAt = 0;
    watchReading(box);
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
    if (restTimer) { root.clearInterval(restTimer); restTimer = null; }  /* #1220 */
    waiting = false;
    touchedAt = 0;
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
    EVERY_MS: EVERY_MS,
    /* #1202: the reading rules, exposed so a test can assert the zero rule
       directly rather than by scraping the drawn panel. told() is the whole
       of "missing is not zero" and it is worth a test of its own. */
    _told: told,
    _pick: pick,
    _asSeconds: asSeconds,
    _rowsOf: rowsOf,
    UNREAD: UNREAD
  };

  /* 2026-09-16 (#1218): A SURFACE SUPPLIES ITS OWN WAY IN.
   *
   * "on the Pine tab, make sure that I'm able to access the Orchestrator icon
   *  on every tab and window. I want to be connected with the orchestrator at
   *  all times."
   *
   * dot() was called from exactly one place in the tree - index.html:894, the
   * DESK SHELL. The tablet never loads index.html; the kiosk injects these
   * same files into the panel document from the APK. So on the tablet nothing
   * ever called it and the orchestrator had no launcher at all - not hidden on
   * some tabs, absent from every one.
   *
   * Safe beside the desk's existing call: dot() opens with
   * `if (dotNode) return dotNode;`, so whichever runs second does nothing. The
   * dismiss flag still wins - dot() returns null when pineOrchDotShut is set,
   * and undot() is still the way back.
   *
   * THE RE-ASSERT, and why it does not break this file's no-polling rule: on
   * the tablet a tab change can tear the view down and take the dot's node
   * with it, and a launcher that survives only until he changes tab is not
   * "every tab". The rule above - "a closed pop-up must ask for nothing at
   * all" - is about asking the STATION. This touches the DOM and never the
   * network, so a closed dot still costs the station nothing. */
  function planted() {
    try {
      return !!(dotNode && root.document && root.document.body
                && root.document.body.contains(dotNode));
    } catch (err) { return false; }
  }

  function plant() {
    try {
      if (planted()) return;
      if (!root.document || !root.document.body) return;
      /* A node that was torn out with its view is not a mounted dot, and the
         cached handle would stop dot() ever building another one. */
      if (dotNode && !planted()) dotNode = null;
      dot();
    } catch (err) { /* a missing launcher must never cost the view */ }
  }

  try {
    if (root.document && root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', plant);
    } else {
      plant();
    }
    /* #1218: UNREF'D. In a browser this is an ordinary repeating timer. Under
       node - which is where the tests run this file - an un-unref'd interval
       keeps the process alive for ever, so the suite would hang rather than
       fail, which is the worse of the two. Browsers have no unref and ignore
       this entirely. */
    var beat = root.setInterval(plant, 4000);
    try { if (beat && typeof beat.unref === 'function') beat.unref(); }
    catch (err) { /* a browser timer: nothing to unref */ }
  } catch (err) { /* older host: the desk's own call still mounts it */ }
})(typeof window !== 'undefined' ? window : globalThis);
