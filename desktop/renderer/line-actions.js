/* HOLD A LINE, AND DECIDE WHAT TO DO WITH IT.
 *
 * "On the Pine tab I want to be able to tap and hold on any piece of
 * dialogue for a few seconds and it basically brings up a pop-up asking me
 * what I want to do with it. So it asks me if I want to place it on a
 * sampler pad, if I want to download it to the tablet, if I want to
 * download it to the local recording folder where I'm extracting things,
 * or if I want to examine it in depth."
 *
 * ONE HANDLER FOR EVERY VIEW. The Script page, the feed, Presentation and
 * the lock screen all show spoken lines, and all of them mark the element
 * with `data-line`. So the hold is bound ONCE, on the document, in the
 * capture phase, and any view that labels its lines gets this for free -
 * including views written later. Four copies of a long-press would be
 * three copies that go stale.
 *
 * A HOLD, NOT A TAP, AND IT MUST NOT STEAL EITHER. These lines already do
 * something on tap (the Script page opens its detail pane) and they sit
 * inside scrolling panes. So: the timer starts on pointerdown, dies on any
 * movement past a few pixels - a scroll is not a hold - and when it fires
 * it marks the element so the click that follows can be swallowed. Getting
 * that wrong makes a list impossible to scroll, which is worse than having
 * no long-press at all.
 */
(function (root) {
  'use strict';

  var HOLD_MS = 600;       /* long enough not to fire on a tap */
  var SLOP = 12;           /* pixels of movement that still counts as still */

  var timer = 0;
  var from = null;
  var startX = 0;
  var startY = 0;
  var swallow = false;

  function api() {
    return root.pineDesktop || {
      get: function () { return Promise.reject(new Error('no bridge')); },
      post: function () { return Promise.reject(new Error('no bridge')); }
    };
  }

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* A spoken line, or nothing. `data-line` is the aired row's id, which is
   * what every station road keys on. */
  function lineAt(target) {
    if (!target || !target.closest) return null;
    var node = target.closest('[data-line]');
    if (!node) return null;
    var id = String(node.dataset.line || '').trim();
    if (!id) return null;
    return {
      id: id,
      said: String(node.textContent || '').trim(),
      node: node
    };
  }

  /* ------------------------------------------------------------ the hold */

  function down(event) {
    clear();
    var line = lineAt(event.target);
    if (!line) return;
    from = line;
    startX = event.clientX || 0;
    startY = event.clientY || 0;
    timer = setTimeout(function () {
      timer = 0;
      swallow = true;
      open(line);
    }, HOLD_MS);
  }

  function move(event) {
    if (!timer) return;
    var dx = Math.abs((event.clientX || 0) - startX);
    var dy = Math.abs((event.clientY || 0) - startY);
    /* A SCROLL IS NOT A HOLD. Without this the feed cannot be dragged
     * without a menu appearing in the middle of it. */
    if (dx > SLOP || dy > SLOP) clear();
  }

  function clear() {
    clearTimeout(timer);
    timer = 0;
    from = null;
  }

  /* The click that follows a long press belongs to the press, not to the
   * element - otherwise holding a script line also opens its detail pane. */
  function maybeSwallow(event) {
    if (!swallow) return;
    swallow = false;
    event.stopPropagation();
    event.preventDefault();
  }

  var wired = false;
  function start() {
    if (wired) return;
    wired = true;
    document.addEventListener('pointerdown', down, true);
    document.addEventListener('pointermove', move, true);
    document.addEventListener('pointerup', clear, true);
    document.addEventListener('pointercancel', clear, true);
    document.addEventListener('click', maybeSwallow, true);
  }

  /* ------------------------------------------------------------ the menu */

  var sheet = null;

  function close() {
    if (sheet) { sheet.remove(); sheet = null; }
  }

  function open(line) {
    close();
    sheet = make('div', 'la-sheet');

    var head = make('div', 'la-head');
    head.appendChild(make('b', '', 'What would you like to do with this?'));
    head.appendChild(make('p', 'la-said', line.said.slice(0, 220)));
    sheet.appendChild(head);

    var list = make('div', 'la-list');
    choice(list, 'Put it on a sampler pad',
      'the next free pad, ready to fire', function (say, bar) { toPad(line, say, bar); });
    choice(list, 'Download it to the tablet',
      'into Downloads / Pine Box', function (say, bar) {
        keep(line, 'downloads', say, bar);
      });
    choice(list, 'Download it to the recording folder',
      'the working folder you extract into', function (say, bar) {
        keep(line, 'recordings', say, bar);
      });
    choice(list, 'Examine it in depth',
      'where it came from, how often it airs, and why', function () {
        close();
        if (root.PineLineDeep) root.PineLineDeep.open(line);
      });
    sheet.appendChild(list);

    var shut = make('button', 'la-close', 'Close');
    shut.type = 'button';
    shut.addEventListener('click', function (e) { e.stopPropagation(); close(); });
    sheet.appendChild(shut);

    document.body.appendChild(sheet);
    if (root.PineDismiss) root.PineDismiss.watch(sheet, close, []);
  }

  function choice(into, title, why, run) {
    /* `run` is handed a `say` and, where it can use one, the bar itself -
     * a download can report real bytes and a pad cut cannot. */
    var row = make('button', 'la-choice');
    row.type = 'button';
    row.appendChild(make('b', '', title));
    row.appendChild(make('i', '', why));
    var said = make('span', 'la-note');
    row.appendChild(said);
    row.addEventListener('click', function (event) {
      event.stopPropagation();
      row.disabled = true;
      /* THE BAR GOES ON THE ROW HE PRESSED. A cut can take ninety seconds
       * - the sampler's own ceiling, because the station is writing and
       * recording audio and a cut queues behind that work - and without
       * this the row simply sat there and invited a second press. */
      var bar = root.PineBusy ? root.PineBusy.attach(row, 'working…') : null;
      var settle = function (ok) { if (bar) bar.finish(ok); row.disabled = false; };
      run(function (text, bad) {
        said.textContent = String(text || '');
        said.classList.toggle('bad', !!bad);
        if (bar) bar.say(String(text || ''));
        /* A message that is not an error but is not the end either -
         * "cutting it…", "fetching the clip…" - leaves the bar running. */
        if (bad) settle(false);
        else if (!/…$/.test(String(text || ''))) settle(true);
      }, bar);
    });
    into.appendChild(row);
  }

  /* --------------------------------------------------------- the actions */

  /* THE SAMPLER'S OWN SEAM, not a second way in. sourceFor and takeable
   * are published precisely so another view can ask the same question this
   * one does rather than guessing from `aired` - the mistake that once
   * offered 7 of about 220 takeable moments. */
  function toPad(line, say, bar) {
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') {
      say('the sampler is not loaded on this terminal', true);
      return;
    }
    var row = {id: line.id, text: line.said};
    try {
      if (typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        say('the station has no clip for this line yet', true);
        return;
      }
    } catch (err) { /* if it will not answer, try the grab anyway */ }
    say('cutting it…');
    Promise.resolve(sampler.grab(row)).then(function (got) {
      if (got === false) say('the sampler would not take it', true);
      else say('on a pad · bank ' + ((root.PineSampler && root.PineSampler.bankIndex)
        ? (root.PineSampler.bankIndex() + 1) : '?'));
    }, function (err) {
      say(String((err && err.message) || err), true);
    });
  }

  /* The bytes never enter the page - the bridge fetches and writes them,
   * and answers with the full path so the operator knows where it went. */
  function keep(line, where, say, bar) {
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.keepClip !== 'function') {
      say('this terminal cannot save files', true);
      return;
    }
    say('fetching the clip…');
    /* The clip is fetched NATIVELY - the bytes never enter the page - so
     * there is no Content-Length here to count against. The sweep is the
     * honest indicator, and the bar says what stage it is at instead of
     * inventing a percentage. */
    bridge.keepClip({
      route: '/api/booth/clip?line=' + encodeURIComponent(line.id),
      said: line.said,
      id: line.id,
      where: where
    }).then(function (got) {
      if (got && got.ok) {
        say('saved to ' + got.where);
      } else {
        say(String((got && got.detail) || 'it could not be saved'), true);
      }
    }, function (err) {
      say(String((err && err.message) || err), true);
    });
  }

  root.PineLineActions = {start: start, open: open, close: close, lineAt: lineAt};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineLineActions;
  }
})(typeof window !== 'undefined' ? window : globalThis);
