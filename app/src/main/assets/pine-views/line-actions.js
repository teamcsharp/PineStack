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
  var OPEN_GUARD_MS = 350; /* a release this soon after opening is the hold's own */
  var DEDUPE_MS = 400;     /* pointerup and the click that follows it are one press */

  var timer = 0;
  var from = null;
  var startX = 0;
  var startY = 0;
  var swallow = false;
  var openedAt = 0;        /* when the sheet last went up, for the guard above */

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

  /* A spoken line, or nothing. Aired surfaces carry `data-line`; prepared
   * calendar/chat/screenplay surfaces carry `data-dialogue-id`. Keeping the
   * lookup here makes the hold sheet genuinely universal instead of making
   * every view grow a slightly different long-press implementation. */
  function lineAt(target) {
    if (!target || !target.closest) return null;
    var node = target.closest('[data-line], [data-dialogue-id], .sp-itin-message');
    if (!node) return null;
    var id = String(node.dataset.line || node.dataset.dialogueId || '').trim();
    if (!id && node.getAttribute) id = String(node.getAttribute('data-line-id') || '').trim();
    if (!id) return null;
    var words = node.querySelector && node.querySelector(
      '[data-dialogue-text], .sp-itin-message-text, .sp-segline-text');
    return {
      id: id,
      said: String((words && words.textContent) || node.textContent || '').trim(),
      node: node
    };
  }

  function spokenLine(line, sfxRow) {
    if (!line || sfxRow) return false;
    var node = line.node;
    if (!node) return false;
    if (node.dataset && node.dataset.spoken === 'true') return true;
    if (node.dataset && node.dataset.spoken === 'false') return false;
    if (node.classList && node.classList.contains('sp-dialogue')) return true;
    if (node.dataset && node.dataset.dialogueId) return true;
    var row = feedRow(line);
    return !!(row && row.id && row.kind !== 'sfx'
      && (row.kind === 'dialogue' || row.kind === 'voice' || row.voice || row.speaker));
  }

  /* ------------------------------------------------------------ the hold */

  function down(event) {
    clear();
    /* A NEW PRESS DISARMS THE OLD SWALLOW. The click the flag was armed for
     * belongs to the hold's release; by the time another finger goes down
     * that click has either arrived and been eaten, or it is never coming
     * (see maybeSwallow for how it goes missing). Either way the flag has
     * no business eating the press that is starting now. */
    swallow = false;
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
   * element - otherwise holding a script line also opens its detail pane.
   *
   * THE DOUBLE CLICK ON THE DESK ("it requires that I click the buttons
   * twice to do the action") LIVED HERE. This flag was a one-shot with no
   * expiry and no idea what it was aimed at: armed when the hold fired, and
   * cleared by the NEXT click, whatever that click was. On the tablet the
   * next click is the hold's own release, and the flag does its job. On the
   * desk that click can simply fail to arrive: the Script page reconciles
   * its lines on a timer and replaces the very node the mouse went down on
   * (script-page.js, the replaceChildren() in its plan repaint and the
   * per-line swap in its reconcile), and Chromium does not dispatch a click
   * whose mousedown target has left the document. So the flag stayed armed,
   * and the first click on a sheet button - Play it, a pad, Close - was
   * eaten HERE, in the capture phase, before the button's own listener could
   * run. The second click worked because the first had spent the flag. The
   * operator saw a menu that needed telling twice.
   *
   * Two rules now, neither of which the old code had: a click INSIDE the
   * sheet is never the hold's click (the hold started on a line, and the
   * line is not in the sheet), and a fresh pointerdown disarms the flag (see
   * down()). Belt and braces beyond that: the sheet's buttons act on
   * pointerup as well as click, so even a swallowed click cannot cost a
   * press - see press() below. */
  function maybeSwallow(event) {
    if (!swallow) return;
    swallow = false;
    if (sheet && event.target && sheet.contains(event.target)) return;
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
    document.addEventListener('contextmenu', function (event) {
      var line = lineAt(event.target);
      if (!line) return;
      event.preventDefault();
      event.stopPropagation();
      clear();
      open(line);
    }, true);
  }

  /* ------------------------------------------------------------ the menu */

  var sheet = null;

  /* Closing the SHEET. The toast and the orb are deliberately not touched:
   * both belong to work that is still running, and taking them down with the
   * menu would hide the answer to the very thing that was just asked for. */
  function close() {
    stopPlaying();
    clearTimeout(voteSayGone);
    voteNow = '';
    if (sheet) { sheet.remove(); sheet = null; }
  }

  function open(line) {
    close();
    sheet = make('div', 'la-sheet');
    sheet.pineLine = line.id;
    openedAt = Date.now();

    /* THE HEADER: the question on the left, the verdict on the right.
     *
     * "At the top just put a up vote and down vote." Two thumbs, Carbon,
     * 36px each, and nothing else up there. Up is "I liked this": the
     * station keeps the recording three times longer and adds the words to
     * the speaker's repertoire - the SFX guy's catchphrases, the host's and
     * co-host's phrases. Down is "that did not work": never reused, and let
     * go when its time comes. The same thumb pressed again takes the vote
     * back. What the station makes of it is said under the header for a
     * few seconds, in its own words, because "kept" and "remembered" are
     * its promises to keep, not this file's. */
    var head = make('div', 'la-head');
    var headRow = make('div', 'la-head-row');
    headRow.appendChild(make('b', '', 'What would you like to do with this?'));
    var votes = make('div', 'la-votes');
    /* [#1200] THE TRASH CAN, for a sound effect only - left of the
     * thumbs, where the finger was pointed. See sfxOf() below. */
    var sfxRow = sfxOf(line);
    if (sfxRow) votes.appendChild(binButton(line, sfxRow));
    votes.appendChild(voteButton(line, 'up', 'c:thumbs-up', 'I liked this'));
    votes.appendChild(voteButton(line, 'down', 'c:thumbs-down', 'This did not work'));
    headRow.appendChild(votes);
    head.appendChild(headRow);
    head.appendChild(make('p', 'la-said', line.said.slice(0, 220)));
    head.appendChild(make('p', 'la-vote-say', ''));
    sheet.appendChild(head);

    var list = make('div', 'la-list');
    /* THE LIKE, IN WORDS, ABOVE EVERYTHING. The thumb in the header says it
     * in a glyph; this row says it in a sentence, with what it does written
     * underneath, so the intent is readable and not only recognisable. It
     * is the same action as the thumb - pressing it on a line already liked
     * takes the like back, exactly as the thumb would. */
    choice(list, 'c:thumbs-up', 'I liked this line',
      'kept three times longer, and they remember it', 'mark', function () {
        return castVote(line, 'up').then(function (got) {
          return { then: (got && got.say) || voteWords(voteNow) };
        });
      });
    /* PLAY IT NEXT, because it is the only one that answers "which line is
     * this?" - and on a screen of six near-identical rap couplets that is
     * the question the hand is usually asking. It is also the only choice
     * here that changes nothing. */
    /* CARBON, from the station's own vendored sprite - never emoji. The two
     * downloads are told apart by their DESTINATION, which is the only thing
     * that differs between them; a download arrow on both would say nothing.
     * There is no c:play in the set, so hearing a line takes the speaker. */
    choice(list, 'c:volume--up--filled', 'Play it',
      'hear this line, here', 'sound', function (stage) {
        return playIt(line, stage.say);
      });
    choice(list, 'c:audio-console', 'Put it on a sampler pad',
      'the next free pad, ready to fire', 'pad', function (stage) {
        return toPad(line, stage);
      });
    if (sfxRow && !sfxRow.deleted) {
      choice(list, 'c:edit', 'Edit and split this sound effect',
        'set in and out points; save separate clips', 'mark', function (stage) {
          return editSfx(line, sfxRow, stage);
        });
    }
    if (spokenLine(line, sfxRow)) {
      choice(list, 'c:bullhorn', 'Make ad with random SFX',
        'use this spoken line; no music', 'mark', function (stage) {
          return makeAdFromLine(line, stage);
        });
      choice(list, 'c:microphone', 'Save dry voice clip',
        'isolated voice only; no SFX or music', 'to:c:folder', function (stage) {
          return saveDryVoice(line, stage);
        });
    }
    choice(list, 'c:screen', 'Download it to the tablet',
      'into Downloads / Pine Box', 'to:c:screen', function (stage) {
        return keep(line, 'downloads', stage);
      });
    choice(list, 'c:folder', 'Download it to the recording folder',
      'the working folder you extract into', 'to:c:folder', function (stage) {
        return keep(line, 'recordings', stage);
      });
    choice(list, 'c:microscope', 'Examine it in depth',
      'where it came from, how often it airs, and why', 'glass', function () {
        return Promise.resolve({ then: 'the record opens' });
      }, function () {
        if (root.PineLineDeep) root.PineLineDeep.open(line);
      });
    sheet.appendChild(list);

    var shut = make('button', 'la-close', 'Close');
    shut.type = 'button';
    press(shut, function () { close(); });
    sheet.appendChild(shut);

    document.body.appendChild(sheet);
    if (root.PineDismiss) root.PineDismiss.watch(sheet, close, []);
    readVote(line);
  }

  /* ONE PRESS, HOWEVER THE ENGINE REPORTS IT.
   *
   * The sheet's buttons act on whichever arrives first of pointerup and
   * click, and count the pair as one press. This is the belt under
   * maybeSwallow's braces: a click can go missing (see there), or be eaten
   * by a capture listener anywhere on the page, and the button still acts
   * on the release the operator actually made.
   *
   * Three things keep the release honest. The button must have seen the
   * pointer go DOWN on it - a release on a sheet that appeared under a held
   * finger is the hold's release, not a choice. A release inside
   * OPEN_GUARD_MS of the sheet opening is likewise the hold's own. And after
   * acting, the same button ignores the click that trails the release by a
   * few hundred milliseconds, or every press would count twice. */
  function press(node, act) {
    var downId = null;
    var actedAt = 0;
    function fire(event) {
      var now = Date.now();
      if (now - actedAt < DEDUPE_MS) return;
      actedAt = now;
      act(event);
    }
    node.addEventListener('pointerdown', function (event) {
      downId = event.pointerId;
    });
    node.addEventListener('pointerup', function (event) {
      if (downId === null || event.pointerId !== downId) return;
      downId = null;
      if (Date.now() - openedAt < OPEN_GUARD_MS) return;
      event.stopPropagation();
      fire(event);
    });
    node.addEventListener('pointercancel', function () { downId = null; });
    node.addEventListener('click', function (event) {
      event.stopPropagation();
      if (Date.now() - openedAt < OPEN_GUARD_MS) return;
      fire(event);
    });
  }

  /* ------------------------------------------------------------ the votes */

  /* What the sheet's line is currently voted, as the station last said it:
   * 'up', 'down' or ''. Read when the sheet opens, rewritten by every
   * answer, forgotten when the sheet closes. */
  var voteNow = '';
  var voteBusy = false;
  var voteSayGone = 0;

  function voteOf(got) {
    var v = String((got && got.vote) || '').toLowerCase();
    return (v === 'up' || v === 'down') ? v : '';
  }

  /* The station's own `say` is preferred; these are only for an answer that
   * came back without one. */
  function voteWords(v) {
    if (v === 'up') return 'kept three times longer, and they remember it';
    if (v === 'down') return 'noted: it will not be used again';
    return 'vote taken back';
  }

  function paintVotes() {
    if (!sheet) return;
    var buttons = sheet.querySelectorAll('.la-vote');
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].dataset.vote === voteNow;
      buttons[i].classList.toggle('on', on);
      buttons[i].setAttribute('aria-pressed', on ? 'true' : 'false');
      buttons[i].disabled = voteBusy;
    }
  }

  /* Under the header, for four seconds - six for a refusal, which is only
   * ever said here. */
  function voteSay(text, bad) {
    if (!sheet) return;
    var say = sheet.querySelector('.la-vote-say');
    if (!say) return;
    say.textContent = String(text || '');
    say.classList.toggle('bad', !!bad);
    say.classList.add('up');
    clearTimeout(voteSayGone);
    voteSayGone = setTimeout(function () {
      if (say.parentNode) say.classList.remove('up');
    }, bad ? 6000 : 4000);
  }

  function readVote(line) {
    Promise.resolve()
      .then(function () {
        return api().get('/api/line/vote?id=' + encodeURIComponent(line.id));
      })
      .then(function (got) {
        /* The sheet may be showing a different line by the time this lands. */
        if (!sheet || sheet.pineLine !== line.id) return;
        voteNow = voteOf(got);
        paintVotes();
      }, function () { /* no vote yet, or no bridge: the thumbs stay plain */ });
  }

  /* The same thumb again takes the vote back - `none` on the wire. The
   * answer's own `vote` is what gets painted, not what was asked for, so
   * the buttons show what the station recorded. */
  function castVote(line, want) {
    if (voteBusy) return Promise.reject(new Error('still voting'));
    var send = (voteNow === want) ? 'none' : want;
    voteBusy = true;
    paintVotes();
    return Promise.resolve()
      .then(function () {
        return api().post('/api/line/vote', { id: line.id, vote: send });
      })
      .then(function (got) {
        voteBusy = false;
        if (got && got.ok === false) {
          throw new Error(String(got.say || got.why || 'the station would not take that'));
        }
        if (sheet && sheet.pineLine === line.id) {
          voteNow = voteOf(got);
          paintVotes();
        }
        return got || {};
      }, function (err) {
        voteBusy = false;
        paintVotes();
        throw err;
      });
  }

  function voteButton(line, which, mark, label) {
    var b = make('button', 'la-vote');
    b.type = 'button';
    b.dataset.vote = which;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-pressed', 'false');
    b.title = label;
    b.appendChild(icon(mark, label));
    press(b, function () {
      castVote(line, which).then(function (got) {
        voteSay((got && got.say) || voteWords(voteNow));
      }, function (err) {
        voteSay(String((err && err.message) || err), true);
      });
    });
    return b;
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
  function icon(name, label) {
    var node = document.createElement('span');
    node.className = 'la-ico';
    if (typeof root.pineIcon === 'function') node.innerHTML = root.pineIcon(name, label);
    else node.setAttribute('data-pine-icon', name);
    return node;
  }

  /* A CHOICE, AND WHAT IT LOOKS LIKE WHILE IT HAPPENS.
   *
   * `kind` says which performance the row puts on when it is pressed:
   *   'pad'        a sampler slides in and the clip flies to a pad
   *   'to:<icon>'  a parcel travels to that destination, with a bar
   *   'glass'      the mark becomes a magnifier and the sheet withdraws
   *   'mark'       the row's own mark swells, for a choice that is a verdict
   *   'sound'      the mark pulses while the line plays
   *
   * `after` runs once the performance has finished and the sheet has gone -
   * for the one choice whose whole point is to open another window, which
   * must not arrive while this one is still on top of it. */
  function choice(into, mark, title, why, kind, run, after) {
    var row = make('button', 'la-choice');
    row.type = 'button';
    row.appendChild(icon(mark));
    row.appendChild(make('b', '', title));
    row.appendChild(make('i', '', why));
    press(row, function () {
      perform(row, mark, title, kind, run, after);
    });
    into.appendChild(row);
  }

  /* ------------------------------------------------------- the performance */

  /* THE WORK HAPPENS WHERE IT WAS ASKED FOR.
   *
   * This walks back the previous behaviour on purpose. The sheet used to
   * vanish the moment a row was pressed, because a menu that just sits there
   * reads as not having heard you. True, and too blunt: it cured "did it hear
   * me" by removing the only surface that could answer "what is it doing".
   *
   * Now the row is promoted - the others fold away, it fills the sheet, and
   * the operation is drawn happening inside it. The sheet leaves when the
   * work is done, so the two questions are answered by the same thing.
   */
  var acting = false;

  function perform(row, mark, title, kind, run, after) {
    if (acting || !sheet) return;
    acting = true;

    /* Every other row folds away. The one pressed stays where it is, which
     * is what makes this read as THAT row acting rather than a new dialog. */
    var list = row.parentNode;
    [].slice.call(list.children).forEach(function (other) {
      if (other !== row) other.classList.add('la-gone');
    });
    row.classList.add('la-acting');
    var shut = sheet.querySelector('.la-close');
    if (shut) shut.classList.add('la-gone');

    var scene = make('div', 'la-scene');
    row.appendChild(scene);
    var note = make('div', 'la-progress-said');
    row.appendChild(note);

    var stage = buildStage(kind, mark, scene, note);
    var closing = false;
    var done = function (ok, text) {
      if (closing) return;
      closing = true;
      stage.finish(ok, text);
      /* Long enough to see the landing, short enough not to be a wait. A
       * refusal is held longer because it is the only place it is said. */
      setTimeout(function () {
        acting = false;
        close();
        if (ok && typeof after === 'function') after();
      }, ok ? 900 : 2200);
    };

    var settled = false;
    var orb = null;

    /* IF IT IS GOING TO TAKE A WHILE, GET OUT OF THE WAY.
     *
     * A cut is the station writing and recording audio with this request
     * queued behind it - the sampler's own ceiling is ninety seconds. A modal
     * sheet held over the script for that long is not progress, it is the
     * screen taken hostage.
     *
     * Two and a half seconds rather than none: a cached cut comes back in a
     * few hundred milliseconds and should finish where the eye already is.
     * Collapsing and re-expanding for that is more movement than the work
     * deserved. Only a job that will actually make you wait earns the corner. */
    var toCorner = setTimeout(function () {
      if (settled || closing) return;
      orb = raiseOrb(mark, title);
      closing = true;                 /* the sheet's part is over */
      acting = false;
      close();
    }, 2500);

    var land = function (ok, text) {
      clearTimeout(toCorner);
      if (orb) { orb.settle(ok, text); return; }
      done(ok, text);
    };

    Promise.resolve()
      .then(function () { return run(stage); })
      .then(function (got) {
        settled = true;
        if (got && got.ok === false) return land(false, got.why || 'it would not');
        land(true, (got && got.then) || stage.finished);
      })
      .catch(function (err) {
        settled = true;
        land(false, (err && err.message) || String(err));
      });
    /* Neither the sheet nor the orb may become a thing that never answers. */
    setTimeout(function () {
      if (settled) return;
      if (orb) orb.say('still cutting…');
      else if (!closing) stage.say('still working…');
    }, 8000);
  }

  /* THE ORB: work that outlived its sheet.
   *
   * Bottom left because that is the one corner of this layout holding
   * nothing - the rail is on the right, the note bar is bottom centre, and
   * the feed's own head is top left.
   *
   * It carries the same Carbon mark the row did, so it is recognisably the
   * thing that was just asked for rather than a new notification. Tapping it
   * dismisses it; it does not re-open the sheet, because the sheet's question
   * has already been answered and re-asking it is not what a tap there
   * means. */
  var orbNode = null;

  function raiseOrb(mark, title) {
    if (orbNode) { orbNode.remove(); orbNode = null; }
    var node = make('div', 'la-orb');
    node.title = title;
    node.appendChild(make('span', 'la-orb-ring'));
    var face = icon(mark);
    face.classList.add('la-orb-face');
    node.appendChild(face);
    var said = make('span', 'la-orb-said');
    node.appendChild(said);
    node.addEventListener('click', function (e) { e.stopPropagation(); fade(); });
    document.body.appendChild(node);
    requestAnimationFrame(function () { node.classList.add('up'); });
    orbNode = node;

    var gone = 0;
    function fade() {
      clearTimeout(gone);
      node.classList.remove('up');
      setTimeout(function () {
        if (node.parentNode) node.remove();
        if (orbNode === node) orbNode = null;
      }, 320);
    }

    return {
      say: function (text) { said.textContent = String(text || ''); },
      settle: function (ok, text) {
        node.classList.add(ok ? 'done' : 'bad');
        said.textContent = String(text || '');
        /* A refusal is held longer: a success is visible on the pad it
         * landed on, and a refusal is only ever said here. */
        gone = setTimeout(fade, ok ? 4200 : 7000);
      }
    };
  }

  /* Each performance is a tiny scene plus a `say`. They share a shape so
   * perform() does not have to know which one it is driving. */
  function buildStage(kind, mark, scene, note) {
    var api = {
      finished: '',
      say: function (text, bad) {
        note.textContent = String(text || '');
        note.classList.toggle('bad', !!bad);
      },
      /* The pad scene wants to know where it landed before it can finish. */
      landed: function () {},
      finish: function (ok, text) {
        scene.classList.add(ok ? 'la-ok' : 'la-bad');
        if (text) api.say(text, !ok);
      }
    };

    if (kind === 'pad') {
      /* THE SAMPLER, SLID IN FROM THE SIDE. Sixteen cells, because that is
       * what a bank is; the chip flies from the row into the one that was
       * actually used, which grab() reports. Without showing WHICH, the
       * operator has to go and hunt for what they just made. */
      var rig = make('div', 'la-rig');
      var grid = make('div', 'la-grid');
      var cells = [];
      for (var i = 0; i < 16; i++) {
        var cell = make('span', 'la-cell');
        cells.push(cell);
        grid.appendChild(cell);
      }
      var chip = make('span', 'la-chip');
      rig.appendChild(chip);
      rig.appendChild(grid);
      scene.appendChild(rig);
      requestAnimationFrame(function () { rig.classList.add('in'); });
      api.say('cutting it…');
      api.landed = function (bank, pad) {
        var at = cells[pad % 16];
        if (!at) return;
        at.classList.add('target');
        /* The chip flies to the cell it is going into, so the eye follows
         * the clip rather than being told about it afterwards. */
        var box = at.getBoundingClientRect();
        var from = chip.getBoundingClientRect();
        chip.style.transform = 'translate(' + Math.round(box.left - from.left)
          + 'px,' + Math.round(box.top - from.top) + 'px) scale(.62)';
        chip.classList.add('flying');
        setTimeout(function () {
          chip.classList.add('landed');
          at.classList.add('filled');
        }, 420);
        api.finished = 'bank ' + (bank + 1) + ' · pad ' + (pad + 1);
      };
      return api;
    }

    if (kind.indexOf('to:') === 0) {
      /* A PARCEL, TRAVELLING. The destination wears the same Carbon mark the
       * row does, so the picture and the words agree about where it is
       * going. */
      var move = make('div', 'la-move');
      var fromMark = icon('c:document');
      fromMark.classList.add('la-end');
      var track = make('span', 'la-track');
      var parcel = make('i', 'la-parcel');
      track.appendChild(parcel);
      var toMark = icon(kind.slice(3));
      toMark.classList.add('la-end');
      move.appendChild(fromMark);
      move.appendChild(track);
      move.appendChild(toMark);
      scene.appendChild(move);
      var bar = make('div', 'la-bar');
      bar.appendChild(make('i', '', ''));
      scene.appendChild(bar);
      requestAnimationFrame(function () { scene.classList.add('running'); });
      api.say('fetching it…');
      /* THE BAR SWEEPS, IT DOES NOT COUNT. keepClip answers once, with a
       * byte count and no progress along the way; a percentage here would be
       * invented. It fills only when the bytes are on disk. */
      return api;
    }

    if (kind === 'glass' || kind === 'mark') {
      /* The same swell for both: a magnifier for the examination, and the
       * row's own thumb for the like, so the verdict is seen being given
       * rather than reported afterwards. */
      var glass = icon(kind === 'glass' ? 'c:search' : mark);
      glass.classList.add('la-glass');
      scene.appendChild(glass);
      requestAnimationFrame(function () { scene.classList.add('running'); });
      api.say(kind === 'glass' ? 'opening the record…' : 'telling the station…');
      return api;
    }

    /* 'sound' */
    var wave = make('div', 'la-wave');
    for (var b = 0; b < 7; b++) wave.appendChild(make('i', '', ''));
    scene.appendChild(wave);
    requestAnimationFrame(function () { scene.classList.add('running'); });
    return api;
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
  /* THE REAL FEED ROW, not a stub of one.
   *
   * The sampler decides whether a line has audio from clip_media/clip_sig,
   * ad_audio, media/sig or aired - all fields of the station's own row. A
   * `{id, text}` stub carries none of them, so every line looked empty:
   * measured on the tablet, 42 lines on screen and 0 takeable, which is why
   * this always said "the station has no clip for this line yet".
   *
   * PineStationFeed holds the ring and keys it by the same id the script
   * screens write into data-line. Searched newest-first, because a re-aired
   * line can appear twice and the later copy is the one whose media is
   * current. */
  function feedRow(line) {
    try {
      var rows = (root.PineStationFeed && root.PineStationFeed.rows)
        ? (root.PineStationFeed.rows() || []) : [];
      for (var i = rows.length - 1; i >= 0; i--) {
        if (rows[i] && String(rows[i].id) === String(line.id)) return rows[i];
      }
    } catch (err) { /* fall through to the stub */ }
    /* Rolled off the 240-row ring. There is genuinely no row any more, and
     * the sampler's own refusal is the honest answer. */
    return { id: line.id, text: line.said };
  }

  /* [#1200] ------------------------------------------- the trash can */

  /* "When I select sound effects, put a icon here of a trash can that I
   * can tap that deletes the file locally on the system so it just gets
   * rid of it permanently."
   *
   * THE CLIP BEHIND A LINE, or null when the line is not a sound effect.
   * The feed row is the authority - it carries `sfx`, the clip's own id.
   * The Script page's node carries the item the station composed, which
   * names the clip's booth row (and, from #1200 on, the clip). A row that
   * has rolled off the ring is still recognisable by what the script
   * says about it; the station resolves the clip from the row id. */
  function sfxOf(line) {
    var row = feedRow(line);
    if (row && (row.sfx || row.kind === 'sfx')) {
      return { sfx: String(row.sfx || ''), line: String(line.id),
               name: String(row.text || ''), deleted: !!row.deleted };
    }
    var item = line.node && line.node.pineItem;
    if (item && (item.tag === 'sting' || item.sfx)) {
      return { sfx: String(item.sfx || ''), line: String(item.line || line.id),
               name: stingName(line.said), deleted: !!item.deleted };
    }
    if (/^A sting off the board:/.test(line.said)) {
      return { sfx: '', line: String(line.id), name: stingName(line.said),
               deleted: /- deleted from the library\.?(\s|$)/.test(line.said) };
    }
    return null;
  }

  /* "A sting off the board: 411 mixtape, bro (0:22)." -> "411 mixtape, bro".
   * The speaker glyph the Script page paints in front of the name is a
   * symbol, not a word, and goes with the length and the deleted note. */
  function stingName(said) {
    var m = /^A sting off the board:\s*([\s\S]*?)(?:\s*\(\d+:\d\d\))?(?:\s*-\s*deleted from the library)?\.?\s*$/
      .exec(String(said || ''));
    var name = m ? m[1] : String(said || '');
    return name.replace(/^[\s\p{So}\p{Cf}️]+/u, '').trim().slice(0, 90);
  }

  function binButton(line, row) {
    var b = make('button', 'la-vote la-bin');
    b.type = 'button';
    b.setAttribute('aria-label', 'Delete this sound effect from the library');
    b.title = 'Delete this sound effect from the library';
    b.appendChild(icon('c:trash-can', 'Delete this sound effect'));
    if (row.deleted) {
      b.disabled = true;
      b.title = 'already deleted';
      b.classList.add('on');
    }
    press(b, function () { askDelete(line, row); });
    return b;
  }

  /* THE QUESTION, IN THE SHEET'S OWN BODY. The list folds away and the
   * sentence with two buttons takes its place. Nothing is sent until the
   * red one is pressed; Keep it puts the list back. */
  function askDelete(line, row) {
    if (!sheet || acting) return;
    var list = sheet.querySelector('.la-list');
    var shut = sheet.querySelector('.la-close');
    if (!list || sheet.querySelector('.la-confirm')) return;
    var ask = make('div', 'la-confirm');
    ask.appendChild(make('p', 'la-confirm-say',
      'Delete ‘' + (row.name || 'this clip') + '’ from the library '
      + 'permanently? It will never be played again and the file is removed.'));
    var buttons = make('div', 'la-confirm-row');
    var yes = make('button', 'la-confirm-yes');
    yes.type = 'button';
    yes.appendChild(icon('c:trash-can'));
    yes.appendChild(make('b', '', 'Delete it for good'));
    var no = make('button', 'la-confirm-no', 'Keep it');
    no.type = 'button';
    buttons.appendChild(yes);
    buttons.appendChild(no);
    ask.appendChild(buttons);
    list.classList.add('la-gone');
    if (shut) shut.classList.add('la-gone');
    list.parentNode.insertBefore(ask, list);
    press(no, function () {
      ask.remove();
      list.classList.remove('la-gone');
      if (shut) shut.classList.remove('la-gone');
    });
    press(yes, function () {
      yes.disabled = true;
      no.disabled = true;
      yes.classList.add('la-busy');
      deleteClip(line, row, ask);
    });
  }

  /* One POST. The station bans the id, forgets the clip on every road that
   * remembered it, and either removes the file or hands it to the desk's
   * courier when the folder is a share this station can only read - its
   * own sentence says which, and that sentence is the toast. */
  function deleteClip(line, row, ask) {
    var body = { id: row.sfx || '', line: row.line || String(line.id),
                 name: row.name || '' };
    laToast('deleting ‘' + (row.name || 'the clip') + '’…');
    return Promise.resolve()
      .then(function () { return api().post('/api/sfx/delete', body); })
      .then(function (got) {
        if (got && got.ok === false) {
          throw new Error(String(got.say || got.why || got.detail || 'the station refused'));
        }
        var sid = String((got && got.deleted) || row.sfx || '');
        markDeleted(line);
        var pads = dropPads(sid, row.line || String(line.id));
        var said = String((got && got.say) || 'deleted');
        if (pads > 0) said += ' · ' + pads + ' pad' + (pads === 1 ? '' : 's') + ' cleared';
        laToast(said);
        close();
        return got;
      }, function (err) {
        laToast('not deleted: ' + saidWhy(err), true);
        if (ask && ask.parentNode) {
          var yes = ask.querySelector('.la-confirm-yes');
          var no = ask.querySelector('.la-confirm-no');
          if (yes) { yes.disabled = false; yes.classList.remove('la-busy'); }
          if (no) no.disabled = false;
        }
        return null;
      });
  }

  /* THE REASON, NOT THE PLUMBING THAT CARRIED IT.
   *
   * The station refuses in words it wrote itself - "that line is not a
   * sound effect", "2 clips are called 'twins' - delete it from the SFX
   * desk". On the desk that sentence comes back through the bridge's
   * fetchJson, which throws the `detail`, through ipcMain.handle, which
   * Electron re-wraps as "Error invoking remote method 'agent:post':
   * Error: <detail>". Put that in a toast and the operator reads a
   * channel name where the answer should be. */
  function saidWhy(err) {
    var why = String((err && (err.message || err.detail)) || err || '');
    why = why.replace(/^Error invoking remote method '[^']*':\s*/, '');
    why = why.replace(/^(?:Error|TypeError):\s*/, '').trim();
    return why || 'it would not';
  }

  /* The row the finger is on reads as gone at once, before any poll. */
  function markDeleted(line) {
    var node = line && line.node;
    if (!node) return;
    try {
      node.classList.add('la-deleted');
      if (!node.querySelector || !node.querySelector('.la-deleted-tag')) {
        node.appendChild(make('span', 'la-deleted-tag', ' · deleted'));
      }
    } catch (err) { /* a node that has already been replaced */ }
  }

  /* Every pad on THIS terminal holding the clip is cleared. Other terminals
   * learn it from /api/dj (`sfx_deleted`), which their sampler watches. */
  function dropPads(sid, lineId) {
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.dropClip !== 'function') return 0;
    try { return Number(sampler.dropClip({ sfx: sid, line: lineId })) || 0; }
    catch (err) { return 0; }
  }

  function toPad(line, stage) {
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') {
      return Promise.resolve({ ok: false,
        why: 'the sampler is not loaded on this terminal' });
    }
    var row = feedRow(line);
    try {
      if (typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        return Promise.resolve({ ok: false,
          why: 'the station has no clip for this line yet' });
      }
    } catch (err) { /* if it will not answer, try the grab anyway */ }

    return Promise.resolve(sampler.grab(row)).then(function (got) {
      /* THE OLD TEST WAS `got === false`, AND grab() NEVER ANSWERS THAT.
       *
       * It answers {ok, bank, pad, meta} - so every failure fell through to
       * the success branch and reported "on a pad - bank ?". Failures have
       * been announcing success. The animation is what turned it up: there
       * was no bank and no pad to fly the clip to. */
      if (!got || got.ok === false) {
        return { ok: false, why: (got && got.why) || 'the sampler would not take it' };
      }
      stage.landed(Number(got.bank) || 0, Number(got.pad) || 0);
      return { ok: true, then: 'on bank ' + ((Number(got.bank) || 0) + 1)
        + ' · pad ' + ((Number(got.pad) || 0) + 1) };
    });
  }

  function editSfx(line, row, stage) {
    var tv = root.PineSfxTv;
    if (!tv || typeof tv.openEditor !== 'function') {
      return Promise.resolve({ok: false, why: 'the clip editor is not loaded here'});
    }
    stage.say('opening the sound effect editor...');
    return Promise.resolve(api().post('/api/sfx/edit/open', {
      clip: row.sfx || '', line: row.line || String(line.id), name: row.name || ''
    })).then(function (got) {
      if (!got || !got.editor_url) {
        return {ok: false, why: String((got && (got.say || got.detail)) ||
          'the editor could not open this sound effect')};
      }
      tv.openEditor(String(got.editor_url), row.name || 'Sound effect');
      close();
      return {ok: true, then: String(got.say || 'editor opened')};
    }, function (err) {
      return {ok: false, why: saidWhy(err)};
    });
  }


  /* The bytes never enter the page - the bridge fetches and writes them,
   * and answers with the full path so the operator knows where it went. */
  function keep(line, where, stage) {
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.keepClip !== 'function') {
      return Promise.resolve({ ok: false, why: 'this terminal cannot save files' });
    }
    stage.say('fetching the clip…');
    /* The clip is fetched NATIVELY - the bytes never enter the page - so
     * there is no Content-Length to count against, and the bar sweeps
     * rather than claiming a percentage nobody measured. */
    return Promise.resolve(bridge.keepClip({
      route: '/api/booth/clip?line=' + encodeURIComponent(line.id),
      said: line.said,
      id: line.id,
      where: where
    })).then(function (got) {
      if (!got || !got.ok) {
        return { ok: false, why: String((got && got.detail) || 'it could not be saved') };
      }
      var size = Number(got.bytes) || 0;
      return { ok: true, then: (size ? Math.round(size / 1024) + ' kB · ' : '')
        + String(got.where || where) };
    }, function (err) {
      return { ok: false, why: String((err && err.message) || err) };
    });
  }

  function makeAdFromLine(line, stage) {
    if (!api().post) return Promise.resolve({ok: false, why: 'station bridge unavailable'});
    stage.say('making the SFX-only ad...');
    return Promise.resolve(api().post('/api/line-actions/make-ad', {
      line_id: line.id, sfx: 'random', music: false
    })).then(function (got) {
      if (!got || got.ok !== true || got.music !== false
          || got.auto_air !== true || got.scheduled !== true
          || !got.ad_id || !got.sfx_id) {
        return {ok: false, why: String((got && (got.detail || got.error))
          || 'the station did not confirm a scheduled SFX-only ad')};
      }
      return {ok: true, then: String(got.say || 'ad made with SFX and no music')};
    }, function (err) {
      return {ok: false, why: String((err && err.message) || err)};
    });
  }

  function saveDryVoice(line, stage) {
    var bridge = root.pineDesktop;
    if (!bridge || !bridge.post || !bridge.keepClip) {
      return Promise.resolve({ok: false, why: 'this terminal cannot save dry voice clips'});
    }
    stage.say('checking the isolated voice clip...');
    return Promise.resolve(bridge.post('/api/line-actions/dry-voice', {
      line_id: line.id
    })).then(function (got) {
      if (!got || got.ok !== true || got.exact !== true || got.voice_only !== true
          || !/^\/api\//.test(String(got.route || ''))) {
        return {ok: false, why: String((got && (got.detail || got.error))
          || 'an exact voice-only clip is not available')};
      }
      return bridge.keepClip({route: got.route, said: line.said, id: line.id,
        where: 'recordings'}).then(function (saved) {
        if (!saved || !saved.ok) {
          return {ok: false, why: String((saved && saved.detail) || 'the clip was not saved')};
        }
        return {ok: true, then: 'dry voice saved to ' + String(saved.where || 'recordings')};
      });
    }, function (err) {
      return {ok: false, why: String((err && err.message) || err)};
    });
  }

  root.PineLineActions = {start: start, open: open, close: close, lineAt: lineAt,
                          sfxOf: sfxOf, stingName: stingName, spokenLine: spokenLine,
                          makeAdFromLine: makeAdFromLine, saveDryVoice: saveDryVoice,
                          editSfx: editSfx};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineLineActions;
  }
})(typeof window !== 'undefined' ? window : globalThis);
