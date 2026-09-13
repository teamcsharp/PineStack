/* LOVE IT, OR DON'T - ON EVERY PLAYER.
 *
 * "Make sure on every media screen that shows a media player that there's
 * an up vote and down vote arrow monochromatic that I'm able to click to
 * basically rate the track that I love it or don't love it so that way it
 * comes up more or less frequently in the broadcast."
 *
 * ONE CONTROL, MOUNTED IN MANY PLACES, because the alternative is five
 * copies of the same three lines and four of them go stale. Listen, Music,
 * the Script page's player, Presentation and the lock screen all mount
 * this same thing.
 *
 * WHAT THE DOWN ARROW ACTUALLY DOES, and why it is labelled the way it is.
 * The station's own contract (app.py:94638) reads:
 *
 *     1 = play it more, -1 = never again, 0 = forget I said anything
 *
 * and a -1 does not merely weight the record down: it pulls it out of the
 * queue and out of the requests, and if it is the record ON AIR the
 * station stops it. That is a good deal stronger than "don't love it", so
 * the arrow says so on the way past rather than letting the operator find
 * out by losing the track he was listening to. The tap still does exactly
 * what the station means by -1; it is only honest about it.
 *
 * PRESSING AGAIN CLEARS. A vote is an opinion, not a sentence, and 0 is
 * the station's own word for taking it back.
 */
(function (root) {
  'use strict';

  var UP = 1;
  var DOWN = -1;
  var CLEAR = 0;

  /* One read of the station's vote table, shared by every mounted pair and
   * refreshed on a rest - five players asking separately would be five
   * requests for one answer. */
  var votes = null;
  var votesAt = 0;
  var VOTES_REST_MS = 20000;
  var asking = null;

  function api() {
    return root.pineDesktop || {
      get: function () { return Promise.reject(new Error('no bridge')); },
      post: function () { return Promise.reject(new Error('no bridge')); }
    };
  }

  function table(force) {
    var now = Date.now();
    if (!force && votes && now - votesAt < VOTES_REST_MS) {
      return Promise.resolve(votes);
    }
    if (asking) return asking;
    asking = api().get('/api/music/votes').then(function (got) {
      var rows = (got && (got.votes || got.rows)) || got || {};
      var map = {};
      if (Array.isArray(rows)) {
        rows.forEach(function (r) {
          if (r && r.id) map[String(r.id)] = Number(r.vote || r.value || 0);
        });
      } else {
        Object.keys(rows).forEach(function (id) {
          var v = rows[id];
          map[String(id)] = Number(
            (v && typeof v === 'object') ? (v.vote || v.value || 0) : v || 0);
        });
      }
      votes = map;
      votesAt = Date.now();
      asking = null;
      return votes;
    }, function () {
      asking = null;
      votes = votes || {};
      return votes;
    });
    return asking;
  }

  function voteOf(id) {
    if (!id || !votes) return 0;
    return Number(votes[String(id)] || 0);
  }

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /**
   * Put a pair of arrows somewhere.
   *
   * @param into  the element to append to
   * @param track a function answering {id, title} for whatever is playing
   *              in THAT player - a function rather than a value, because
   *              the record changes under the control and a pair wired to
   *              a stale id votes on the wrong song.
   * @param say   optional: how to tell the operator what happened
   */
  function mount(into, track, say) {
    if (!into || typeof track !== 'function') return null;
    var wrap = make('div', 'pv-votes');
    var up = make('button', 'pv-vote pv-up', '▲');
    var down = make('button', 'pv-vote pv-down', '▼');
    up.type = 'button'; down.type = 'button';
    up.title = 'Play this more often';
    down.title = 'Never play this again — and stop it now';
    up.setAttribute('aria-label', up.title);
    down.setAttribute('aria-label', down.title);
    wrap.appendChild(up);
    wrap.appendChild(down);
    into.appendChild(wrap);

    function tell(text, bad) {
      if (typeof say === 'function') { say(text, bad); return; }
      wrap.dataset.said = text;
      clearTimeout(wrap.__timer);
      wrap.__timer = setTimeout(function () { wrap.dataset.said = ''; }, 5000);
    }

    function paint() {
      var now = track() || {};
      var mine = voteOf(now.id);
      up.classList.toggle('on', mine > 0);
      down.classList.toggle('on', mine < 0);
      var known = !!now.id;
      up.disabled = !known;
      down.disabled = !known;
      wrap.hidden = !known;
    }

    function send(want) {
      var now = track() || {};
      if (!now.id) return;
      var mine = voteOf(now.id);
      /* Pressing the arrow that is already lit takes the vote back. */
      var vote = (mine === want) ? CLEAR : want;

      votes = votes || {};
      votes[String(now.id)] = vote;   /* show it at once */
      paint();

      api().post('/api/music/vote', {id: now.id, vote: vote})
        .then(function () {
          if (vote === UP) tell('more of this one');
          else if (vote === DOWN) tell('never again — taken off the air');
          else tell('vote cleared');
          table(true).then(paint);
        }, function (err) {
          /* Put the button back where it was: a control that lies about
           * what the station holds is worse than one that refuses. */
          table(true).then(paint);
          tell('the station refused that: '
            + ((err && err.message) || err), true);
        });
    }

    up.addEventListener('click', function (e) { e.stopPropagation(); send(UP); });
    down.addEventListener('click', function (e) { e.stopPropagation(); send(DOWN); });

    table(false).then(paint);
    paint();

    return {element: wrap, paint: paint, refresh: function () {
      return table(true).then(paint);
    }};
  }

  var api2 = {mount: mount, table: table, voteOf: voteOf};
  root.PineVote = api2;
  if (typeof module !== 'undefined' && module.exports) module.exports = api2;
})(typeof window !== 'undefined' ? window : globalThis);
