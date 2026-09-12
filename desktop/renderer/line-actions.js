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

  /* Closing the SHEET. The toast is deliberately not touched: it belongs to
   * work that is still running, and taking it down with the menu would hide
   * the answer to the very thing that was just asked for. */
  function close() {
    stopPlaying();
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
    /* PLAY IT FIRST, because it is the only one that answers "which line is
     * this?" - and on a screen of six near-identical rap couplets that is
     * the question the hand is usually asking. It is also the only choice
     * here that changes nothing. */
    /* CARBON, from the station's own vendored sprite - never emoji. The two
     * downloads are told apart by their DESTINATION, which is the only thing
     * that differs between them; a download arrow on both would say nothing.
     * There is no c:play in the set, so hearing a line takes the speaker. */
    choice(list, 'c:volume--up--filled', 'Play it',
      'hear this line, here', function (say) { playIt(line, say); });
    choice(list, 'c:audio-console', 'Put it on a sampler pad',
      'the next free pad, ready to fire', function (say, bar) { toPad(line, say, bar); });
    choice(list, 'c:screen', 'Download it to the tablet',
      'into Downloads / Pine Box', function (say, bar) {
        keep(line, 'downloads', say, bar);
      });
    choice(list, 'c:folder', 'Download it to the recording folder',
      'the working folder you extract into', function (say, bar) {
        keep(line, 'recordings', say, bar);
      });
    choice(list, 'c:microscope', 'Examine it in depth',
      'where it came from, how often it airs, and why', function () {
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

  /* WHERE THE WORK REPORTS FROM ONCE THE MENU HAS GONE.
   *
   * One line at the foot of the screen, outliving the sheet that started it.
   * A cut can run ninety seconds and the operator should be able to watch it
   * without the menu they already dismissed sitting over the script.
   *
   * It carries the same shape the row bar did - say/finish - so the actions
   * below did not have to learn anything new. */
  var toast = null;
  var toastGone = 0;

  function laToast(text, bad) {
    if (!toast) {
      toast = make('div', 'la-toast');
      document.body.appendChild(toast);
    }
    toast.textContent = String(text || '');
    toast.classList.toggle('bad', !!bad);
    toast.classList.add('up');
    clearTimeout(toastGone);
    /* Still working: leave it. A refusal is worth longer than a success,
     * because a success is usually visible somewhere else - on a pad, in a
     * folder - and a refusal is only ever here. */
    if (/\u2026$/.test(String(text || ''))) return;
    toastGone = setTimeout(function () {
      if (!toast) return;
      toast.classList.remove('up');
      setTimeout(function () { if (toast) { toast.remove(); toast = null; } }, 260);
    }, bad ? 6000 : 3200);
  }

  /* ONE CARBON GLYPH, inheriting the colour of the text beside it.
   *
   * pineIcon() hands back an <svg><use href="#pi-..."> against a sprite the
   * icon script injects at load. If that script is not on the page - a bare
   * host, a test harness - the data attribute is left for pineIconUpgrade()
   * to fill in later, and until then the row simply has no picture, which is
   * the right way to fail. */
  function icon(name) {
    var node = document.createElement('span');
    node.className = 'la-ico';
    if (typeof root.pineIcon === 'function') node.innerHTML = root.pineIcon(name);
    else node.setAttribute('data-pine-icon', name);
    return node;
  }

  function choice(into, mark, title, why, run) {
    var row = make('button', 'la-choice');
    row.type = 'button';
    row.appendChild(icon(mark));
    row.appendChild(make('b', '', title));
    row.appendChild(make('i', '', why));
    row.addEventListener('click', function (event) {
      event.stopPropagation();
      /* THE MENU GOES AT ONCE. It is dismissed BY being chosen from; one
       * that stays reads as not having heard you, and the old version then
       * reported refusals into a sheet the operator had already finished
       * with. The work carries on and speaks from the foot of the screen. */
      var held = sheet;
      sheet = null;
      if (held) held.remove();
      run(laToast, {
        say: function (text) { laToast(text); },
        finish: function (ok) { if (!ok) return; }
      });
    });
    into.appendChild(row);
  }

  /* --------------------------------------------------------- the actions */

  /* HEAR IT, WITHOUT PUTTING IT ANYWHERE.
   *
   * Through the sampler's own sourceFor, so this asks the same question the
   * pad grab asks and cannot disagree with it about which line has audio -
   * the mistake that once offered 7 takeable moments out of about 220.
   *
   * The broadcast is DUCKED while it plays, the same as a pad: the operator
   * pressed this to hear one line, and hearing it under a record is not
   * hearing it. The element is marked as the sampler's own so the air tap
   * does not record this audition back into its own ring. */
  var playing = null;

  function stopPlaying() {
    if (!playing) return;
    try { playing.pause(); } catch (err) { /* already gone */ }
    playing = null;
    if (root.PineAir) root.PineAir.release('audition');
  }

  function playIt(line, say) {
    stopPlaying();
    var sampler = root.PineSampler;
    var source = sampler && typeof sampler.sourceFor === 'function'
      ? sampler.sourceFor({id: line.id, text: line.said}) : null;
    if (!source) {
      /* sourceFor needs the ROW, not a stub - it reads aired/media/sig. Fall
       * back to the clip route, which is what the row would have resolved to
       * anyway for a line that aired. */
      source = {url: '/api/booth/clip?line=' + encodeURIComponent(line.id)};
    }
    say('playing…');
    var audio = new Audio(source.url);
    if (root.PineAir && root.PineAir.mine) root.PineAir.mine(audio);
    /* EVERY ROAD OUT RELEASES, not just the happy one. `ended` is the road
     * that was wired first and it is the one that did not fire: measured,
     * the clip finished, no event arrived, and the radio stayed muted with
     * nothing playing. `pause` and `emptied` catch a stalled or replaced
     * element, and PineAir's own ceiling catches whatever is left. */
    ['ended', 'pause', 'emptied'].forEach(function (when) {
      audio.addEventListener(when, function () {
        if (playing !== audio) return;
        stopPlaying();
        say(when === 'ended' ? 'played' : '');
      });
    });
    audio.addEventListener('error', function () {
      stopPlaying();
      say('there is no audio behind that line', true);
    });
    /* Ducked for as long as the clip lasts once its length is known, and no
     * longer. Until then PineAir's ceiling is the backstop. */
    audio.addEventListener('loadedmetadata', function () {
      if (playing === audio && root.PineAir) {
        root.PineAir.duck('audition', audio.duration);
      }
    });
    if (root.PineAir) root.PineAir.duck('audition');
    playing = audio;
    audio.play().then(function () {
      say('playing…');
    }, function (err) {
      stopPlaying();
      say(String((err && err.message) || err), true);
    });
  }

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
