/* window.PineListenModel - everything Listen and Music KNOW, with no DOM.
 *
 * Two views, one body of arithmetic. Listen is lean-back and Music is
 * music-centric, but they answer the same questions - what is sounding,
 * how far through it is, what comes next, what the shelf holds - so the
 * answers live here once and both views paint them. Nothing in this file
 * touches document, window timers or fetch; it takes a payload and a
 * number and returns a shape. That is what makes it testable from
 * node:test without a browser, the same way lcd-dialogue.js is.
 *
 * ONE POLLER, AND WHY THIS FILE EXISTS AT ALL.
 *
 * Measured on 2026-09-11: 38 concurrent requests in flight to the station
 * produced a 46-second media stall on the tablet - the tablet played no
 * audio at all. The station's own comment (app.py:154692) sets the only
 * cadence that is allowed here: "the round clock every 250 ms,
 * speaking_now every 4 s." window.PineStationFeed already runs exactly
 * that - ONE /api/dj poll every four seconds and a local 250 ms tick -
 * and both of these views subscribe to it rather than fetching anything
 * of their own. So this file must be able to derive its whole picture
 * from a single /api/dj payload plus a corrected clock. It can, and the
 * surprising part is how much:
 *
 *   now          the record turning, with url, art, seconds   (app.py:25217)
 *   coming       the record being introduced but not started  (app.py:25252)
 *   upcoming[]   the next twenty queued/requested tracks      (app.py:25283)
 *   played[]     the last ten records, newest first           (app.py:25368)
 *   requests     how many of the queue were asked for
 *   chat[]       240 rows of booth scrollback
 *   stream_now   the per-turn timeline of the round on air    (app.py:25405)
 *   speaking_now which line is live right now                 (app.py:25169)
 *   server_ms    the station's clock at the moment it answered (app.py:21821)
 *   started_ms   when the record on air started, same clock   (app.py:21822)
 *
 * So the playlist, the up-next, the recently-played and the whole
 * now-playing block cost ZERO extra requests. Only four things are not on
 * that payload and have to be asked for: the shelf sample
 * (/api/music/browse), the running order (/api/schedule/hours), the
 * request book (/api/dj/requested) and the gallery (/api/generations).
 * Every one of those is fetched ONCE on mount and thereafter only when
 * the operator presses its own refresh. They are not pollers and must
 * never become them.
 *
 * DO NOT USE lean=1. DJ_LEAN_DROP (app.py:94128) drops stream_now, which
 * is where the playhead inside a spoken round lives, and truncates chat
 * to 20 rows. The feed already refuses it; this is the reason.
 *
 * THE PLAYHEAD IS FREE, AND THAT IS THE BEST FINDING IN HERE.
 *
 * The desktop's own follower polls a SECOND route, /api/radio/clock
 * (app.py:93327), four times a minute purely to keep a record in sync,
 * and computes (app.py:154655):
 *
 *     target = (clock.server_ms - clock.started_ms) / 1000 + age
 *
 * where `age` is how long ago that answer arrived. PineStationFeed
 * already corrects for exactly that: its clock() is
 * Date.now() + (server_ms - Date.now-at-poll), so
 *
 *     (correctedClock - started_ms) / 1000
 *
 * is algebraically the same number. The playhead therefore comes off the
 * feed we are already subscribed to, at 250 ms, and NEITHER VIEW NEEDS
 * /api/radio/clock. That is one whole poller not added, which given the
 * 38-requests measurement is the point.
 */
(function (root) {
  "use strict";

  /* app.py:112182 - AIRLOG_KEEP_S = 48 * 3600. Line ids resolve for two
   * days and the media is then swept. Anything in these views that points
   * at a spoken line is therefore perishable, and the UI says so rather
   * than offering a grab that will fail. */
  const MEDIA_WINDOW_S = 48 * 3600;

  /* ------------------------------------------------------------- clocks */

  /* The station's clock minus this machine's, in milliseconds. `polledAt`
   * is Date.now() at the instant the payload landed. Positive means the
   * station is ahead of us. This is the same arithmetic PineStationFeed
   * does; it is restated here so it can be tested without a browser. */
  function skewOf(station, polledAt) {
    const server = Number((station || {}).server_ms);
    if (!Number.isFinite(server) || !server) return 0;
    return server - Number(polledAt);
  }

  /* Where the record is, in seconds, from a clock that has ALREADY had
   * the skew applied (PineStationFeed's payload.at, or localNow +
   * skewOf(...)).
   *
   * Three refusals, each of which was a visible bug in something else
   * before it was a rule here:
   *
   *  - No record: started_ms is 0 when `now` is falsy (app.py:21822), and
   *    (at - 0)/1000 is fifty-eight years. Answer "not following".
   *  - Paused: elapsed keeps running through a pause on this road, so an
   *    extrapolated playhead walks off the end of a frozen record. #1145
   *    is the same bug in the desktop's follower. Report the position the
   *    station last stated and stop moving it.
   *  - Past the end: the desktop clamps to seconds - 0.75 (app.py:154657)
   *    so a follower never seeks into the run-out. Same clamp here, for
   *    the same reason: a progress bar that reads 4:13 of 4:12 looks
   *    broken even when the arithmetic is right.
   */
  function playhead(station, correctedAt) {
    const state = station || {};
    const track = state.now || null;
    const started = Number(state.started_ms || 0);
    const length = Math.max(0, Number((track || {}).seconds || 0));
    if (!track || !started) {
      return {following: false, position: 0, length: 0, remaining: 0,
              fraction: 0, paused: !!state.paused};
    }
    if (state.paused) {
      /* `remaining` is computed on the station at poll time
       * (app.py:25281) and is the only honest figure while frozen. */
      const left = Math.max(0, Number(state.remaining || 0));
      const at = length ? Math.max(0, length - left) : 0;
      return {following: true, paused: true, position: at, length,
              remaining: left, fraction: length ? at / length : 0};
    }
    let position = (Number(correctedAt) - started) / 1000;
    if (!Number.isFinite(position) || position < 0) position = 0;
    if (length) position = Math.min(position, Math.max(0, length - 0.75));
    return {
      following: true, paused: false, position, length,
      remaining: length ? Math.max(0, length - position) : 0,
      fraction: length ? Math.min(1, position / length) : 0
    };
  }

  /* -------------------------------------------------------- now playing */

  /* WHAT IS SOUNDING, as one sentence the big type can hold.
   *
   * A radio station is two things at once: a record turning and a pair of
   * voices over the top of it. The lean-back screen has one headline, so
   * it has to choose, and it chooses THE VOICE when there is one - a
   * spoken line lasts seconds and is the thing that just changed, while
   * the record has been there for three minutes and is still named
   * underneath. The alternative (record always wins) was tried on paper
   * and makes the screen look frozen through every round of banter, which
   * is most of what the station does.
   *
   * `speaking` is handed in rather than recomputed: PineStationFeed
   * already works out which turn of stream_now is live, at 250 ms, and
   * two answers to that question would eventually disagree. */
  function nowPlaying(station, speaking, clock) {
    const state = station || {};
    const track = state.now || null;
    const bar = playhead(state, clock);
    const out = {
      kind: "quiet", headline: "", sub: "", why: "",
      track: track ? {
        id: String(track.id || ""), title: String(track.title || ""),
        artist: String(track.artist || ""), album: String(track.album || ""),
        art: String(track.art || ""), seconds: Number(track.seconds || 0)
      } : null,
      bar, voice: null, paused: !!state.paused, on: !!state.on
    };
    if (speaking && (speaking.text || speaking.name || speaking.who)) {
      out.voice = {
        id: String(speaking.id || ""),
        who: String(speaking.name || speaking.who || "the booth"),
        text: String(speaking.text || "")
      };
    }
    /* 2026-09-15 (#1206): THE RECORD KEEPS THE HEADLINE.
     *
     * The note above argues the other way and was written before anyone had
     * watched it: a spoken line is the thing that just changed, and "record
     * always wins" was tried ON PAPER and looked like it would freeze the
     * screen through every round of banter.
     *
     * The screen disproved it. The operator sent a picture of a gallery
     * round's analysis - four full-width lines at headline size - standing
     * where the song should be, with the SAME TEXT scrolling in the marquee
     * underneath it. "instead of taking over the header for the song, it
     * should just be part of the scrolling marquee with the text below."
     *
     * Two things the original reasoning could not have known. The spoken line
     * is already on screen in the marquee, so the headline was a second copy
     * of it - which is the very fault the markup note at plNow says the first
     * draft had. And a gallery line is not a line: it is a paragraph, and it
     * pushes the record, the artist and the cover out of the way.
     *
     * Nothing freezes. The bar, the clock, the meters, the marquee, the
     * spectrogram and what-is-next all keep moving. The only thing that stops
     * changing is the line naming the record, which is the line that should
     * be still while the record plays.
     *
     * `kind` stays "voice" so the speaker's name, the marquee and every other
     * reader behave exactly as before. Only the headline moves. */
    if (track) {
      out.kind = out.voice && out.voice.text ? "voice" : "track";
      out.headline = out.track.title || "an untitled track";
      out.sub = [out.track.artist, out.track.album].filter(Boolean).join(" · ");
      return out;
    }
    /* No record. The voice keeps the headline here, and must: a screen
     * reading "quiet" while the pair are plainly talking is a worse lie than
     * the one above, and the marquee alone is too small to carry the room. */
    if (out.voice && out.voice.text) {
      out.kind = "voice";
      out.headline = out.voice.text;
      out.sub = out.voice.who;
      return out;
    }
    /* Nothing is playing. WHICH kind of nothing is the useful part, and
     * the three are genuinely different: switched off, deliberately off
     * air with the booth still working behind it, or on and between
     * things. A single "quiet" would hide a stopped station behind what
     * looks like a gap. */
    out.headline = "quiet";
    if (!state.on) { out.why = "the station is not running"; out.sub = "off"; }
    else if (state.paused) {
      out.why = "off air - the booth is still working, and banking it";
      out.sub = "paused";
    } else {
      const wait = Number(state.talk_next_in);
      out.why = Number.isFinite(wait) && wait > 0
        ? "the pair are due to say something in about "
          + Math.round(wait) + "s"
        : "between records";
      out.sub = "on air";
    }
    return out;
  }

  /* ----------------------------------------------------------- what next */

  /* `coming` is a record being INTRODUCED but not started (app.py:25252,
   * #176/#178) - it exists precisely so a screen does not leave the last
   * track up as though it were still on. It outranks the queue, because
   * it is what the pair are talking about right now. */
  function whatsNext(station) {
    const state = station || {};
    const queue = Array.isArray(state.upcoming) ? state.upcoming : [];
    const coming = state.coming || null;
    const head = coming || queue[0] || null;
    return {
      when: coming ? "introducing" : head ? "queued" : "nothing",
      title: head ? String(head.title || "") : "",
      artist: head ? String(head.artist || "") : "",
      id: head ? String(head.id || "") : "",
      art: head ? String(head.art || "") : "",
      queued: queue.length,
      requests: Math.max(0, Number(state.requests || 0))
    };
  }

  /* The queue and the recently-played, both already on /api/dj. `played`
   * is `list(reversed(_RADIO["history"][-10:]))` (app.py:25368) - ten
   * rows, newest first, and it costs nothing. /api/music/played would
   * give sixty with vote state, at the price of a request; the ten are
   * enough for a screen and the sixty are a button press away. */
  function queueRows(station) {
    return (Array.isArray((station || {}).upcoming)
      ? station.upcoming : []).map(trackRow);
  }

  function playedRows(station) {
    return (Array.isArray((station || {}).played)
      ? station.played : []).map(trackRow);
  }

  function trackRow(raw) {
    const row = raw || {};
    return {
      id: String(row.id || ""),
      title: String(row.title || ""),
      artist: String(row.artist || ""),
      album: String(row.album || ""),
      art: String(row.art || ""),
      url: String(row.url || ""),
      seconds: Number(row.seconds || 0)
    };
  }

  /* ---------------------------------------------------------- the shelf */

  /* /api/music/browse (app.py:93073) is NOT a catalogue listing. 35,000
   * tracks are too many to list, so it hands back a stable random sample,
   * seeded by the hour unless a seed is passed. Two consequences the UI
   * has to be honest about: the same page comes back all hour unless a
   * new seed is asked for, so the refresh control sends one; and "the
   * shelf" is a handful of the library, never the library. */
  function shelfRows(payload) {
    const rows = Array.isArray((payload || {}).results) ? payload.results : [];
    return rows.map(trackRow).filter((row) => row.id);
  }

  function shelfTotal(payload) {
    return Math.max(0, Number((payload || {}).total || 0));
  }

  /* --------------------------------------------------------- the requests */

  /* /api/dj/requested (app.py:95021) - every song ever asked for AND
   * fulfilled, newest first, capped at 60. Not /api/dj/requests, which is
   * a tally (`top` by count) rather than a book. */
  function requestRows(payload) {
    const rows = Array.isArray((payload || {}).requested)
      ? payload.requested : [];
    return rows.map((raw) => ({
      title: String((raw || {}).title || ""),
      artist: String((raw || {}).artist || ""),
      count: Math.max(0, Number((raw || {}).count || 0)),
      last: Math.max(0, Number((raw || {}).last || 0))
    })).filter((row) => row.title);
  }

  /* ------------------------------------------------------ running order */

  /* /api/schedule/hours (app.py:47704 -> schedule_hours_view app.py:47515)
   * answers with whole hours, each carrying its slots. Flattened to a
   * single list here because the Music view shows the hour on air and the
   * one after it as one running order, not as two tables.
   *
   * `state` is the booth's own position and `past` is derived from it
   * (app.py:47629) - deliberately NOT from the wall clock, because #963
   * was exactly that mistake: a nominal walk of the minutes greyed out
   * every remaining tile late in an hour whether or not the booth had
   * reached them. So this trusts `state`/`past` as given and never
   * recomputes "has this aired" from starts_epoch. */
  function scheduleRows(payload, limit) {
    const hours = Array.isArray((payload || {}).hours) ? payload.hours : [];
    const out = [];
    const cap = Number.isFinite(limit) ? limit : 40;
    for (const hour of hours) {
      const slots = Array.isArray((hour || {}).slots) ? hour.slots : [];
      for (const slot of slots) {
        if (out.length >= cap) return out;
        out.push({
          hour: String((hour || {}).label || ""),
          key: String((hour || {}).key || ""),
          id: String((slot || {}).id || ""),
          kind: String((slot || {}).kind || ""),
          label: String((slot || {}).label || ""),
          minutes: Number((slot || {}).minutes || 0),
          at: String((slot || {}).starts_at || ""),
          enabled: (slot || {}).enabled !== false,
          state: String((slot || {}).state || "coming"),
          live: String((slot || {}).state || "") === "on air",
          past: !!(slot || {}).past
        });
      }
    }
    return out;
  }

  /* ---------------------------------------------------------- the gallery */

  /* STILLS ONLY, AND THAT IS A DECISION.
   *
   * /api/generations/image/{filename} (app.py:112044) serves video too,
   * and the plan's video wall belongs to the Presentation view. Listen
   * does not take it, for two measured reasons: that route returns a
   * whole Response with NO Range support, so a long clip cannot seek and
   * must be held entire; and Listen is the view most likely to be left on
   * a 4 GB tablet for eight hours, where a rotating set of decoded videos
   * is the classic way to run a WebView out of memory. A still costs one
   * decode and is replaced, not accumulated.
   *
   * The paper filter matches lcd-gallery.js: a regenerated picture can
   * keep Gazette tags, so tags alone never hide an ordinary picture. */

  /* A bare filename, not a path and not a control sequence - the same
   * guard lcd-gallery.js applies, because this string is interpolated
   * straight into /api/generations/image/. Written as a loop rather than
   * a character class so the control range cannot be mangled by whatever
   * edits this file next; hyphens, spaces and dots are ORDINARY in
   * ComfyUI output and must never be rejected. */
  function filenameSafe(name) {
    for (let i = 0; i < name.length; i += 1) {
      const code = name.charCodeAt(i);
      if (code < 32 || code === 127) return false;
      if (name[i] === "/" || name[i] === "\\") return false;
    }
    return true;
  }

  function galleryStills(payload) {
    const rows = Array.isArray((payload || {}).generations)
      ? payload.generations : [];
    const seen = new Set();
    const files = [];
    for (const row of rows) {
      if (!row || !Array.isArray(row.files)) continue;
      const tags = String(row.tags || "");
      const paper = row.kind === "paper" || row.model === "gazette"
        || (tags.indexOf("gazette ") === 0 && row.files.some(
          (name) => String(name).split("/").pop().indexOf("gazette-") === 0));
      if (paper) continue;
      for (const name of row.files) {
        if (typeof name !== "string" || !name || name.length > 200) continue;
        if (name.indexOf("..") >= 0) continue;
        if (!filenameSafe(name)) continue;
        if (!/\.(png|jpe?g|webp)$/i.test(name)) continue;
        if (seen.has(name)) continue;
        seen.add(name);
        files.push(name);
      }
    }
    return files;
  }

  /* ------------------------------------------------------------- the grab */

  /* THE NEXT FREE PAD.
   *
   * The sampler's own gesture is a drag onto a chosen pad. Lean-back has
   * no drag and no chosen pad, so "grab this" has to pick one, and the
   * rule is: the first empty pad of the bank on screen, then the first
   * empty pad of any later bank, then any earlier bank. It never
   * overwrites - a full set of banks is reported as full and the operator
   * is told to clear one, because silently replacing a pad someone
   * recorded an hour ago is exactly the kind of quiet destruction the
   * sampler's CHOP undo exists to prevent. */
  function firstFreePad(layout, bank) {
    if (!Array.isArray(layout) || !layout.length) return null;
    const banks = layout.length;
    const start = Math.max(0, Math.min(banks - 1, Number(bank) || 0));
    for (let step = 0; step < banks; step += 1) {
      const b = (start + step) % banks;
      const pads = Array.isArray(layout[b]) ? layout[b] : [];
      for (let p = 0; p < pads.length; p += 1) {
        if (!pads[p]) return {bank: b, pad: p};
      }
    }
    return null;
  }

  /* WHICH MOMENT "grab this" MEANS.
   *
   * Not the record. sourceFor() in sampler.js would happily take
   * station.now.url - a signed /music/<id> - because it looks like media
   * with no text, and a four-minute track decodes to roughly 45 MB of
   * PCM against a footprint the sampler already warns about at 16 pads.
   * A record is also not a moment: it is available in the library
   * forever and can be put on again from the Music view in one tap.
   *
   * So the grab takes THE VOICE: the line on air if one is, otherwise the
   * most recent takeable row in the feed - the thing that just happened,
   * which is what the operator's thumb is reaching for. `takeable` is
   * handed in so this file never has to know how sampler.js decides; that
   * knowledge lives in sourceFor() and must not be copied. */
  function grabTarget(rows, speaking, takeable, at) {
    const list = Array.isArray(rows) ? rows : [];
    const can = typeof takeable === "function" ? takeable : () => true;
    if (speaking && speaking.id) {
      const live = list.find((row) => String(row.id) === String(speaking.id));
      if (live && can(live) && !mediaStale(live, at)) {
        return {row: live, why: "the line on air"};
      }
    }
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const row = list[i];
      if (!row || !can(row) || mediaStale(row, at)) continue;
      return {row, why: "the last thing said"};
    }
    return {row: null, why: "nothing in the feed has audio behind it yet"};
  }

  /* app.py:112182 - the media behind a line is swept at 48 h. A row older
   * than that still reads perfectly well in the feed and its clip fetch
   * will 404, so the grab refuses it with a sentence instead of a
   * timeout. Rows with no timestamp at all are treated as fresh: the live
   * ring is by definition recent, and refusing on a missing field would
   * make the button useless. */
  function mediaStale(row, at) {
    const stamp = Number((row || {}).air_at || (row || {}).ts || 0);
    if (!stamp) return false;
    const now = Number(at) || Date.now();
    return (now / 1000) - stamp > MEDIA_WINDOW_S;
  }

  /* ------------------------------------------------------- the sleep timer */

  /* THE SLEEP TIMER SILENCES THIS TERMINAL, NEVER THE STATION.
   *
   * The tempting implementation is the air-pause or /api/dj/stop, and
   * both are wrong: the station is shared - a Nabu, a Pine Box, a public
   * listen link, another terminal in another room - and a tablet going to
   * sleep on a bedside table must not take the show off the air for the
   * house. The station has no per-listener volume either; what it has is
   * a routing table and each page's own desk.
   *
   * So this is a pure countdown that ends in local silence, and the view
   * carries it out through seams that already exist (the shell's own
   * volume slider, or PineTerminalAudio.mute, which deliberately skips
   * the sampler). The last minute is a fade rather than a cut, because a
   * radio that stops mid-word wakes you up. */
  const FADE_S = 45;

  function sleepPlan(minutes, at) {
    const mins = Number(minutes);
    if (!Number.isFinite(mins) || mins <= 0) return null;
    const started = Number(at) || Date.now();
    return {minutes: mins, started, until: started + mins * 60000};
  }

  function sleepTick(plan, at) {
    if (!plan) return {state: "off", left: 0, gain: 1};
    const now = Number(at) || Date.now();
    const left = (plan.until - now) / 1000;
    if (left <= 0) return {state: "done", left: 0, gain: 0};
    if (left <= FADE_S) {
      return {state: "fading", left, gain: Math.max(0, left / FADE_S)};
    }
    return {state: "running", left, gain: 1};
  }

  /* ==================================================== THE TRACK DETAIL ==
   *
   * "Be able to tap on every song in the queue and be able to expand it and
   *  see the dialogue generated for it, see the analysis that's done for
   *  it, see what online research has been done for it, see what we've
   *  queued up for the host to say about this particular track and what
   *  they've analyzed from it. And this is for each and every track."
   *
   * FOUR ASKS, FIVE STORES, AND THEY ARE NOT THE SAME SHAPE. Everything
   * below was established by reading app.py and probing the live station
   * on 2026-09-11 rather than by inference, because three of the obvious
   * guesses were wrong. What is actually there:
   *
   *  1. THE ANALYSIS is SongSight. /api/song-crystals (app.py:93391)
   *     returns every crystal WITH the library track behind it resolved by
   *     crystal_with_track (app.py:93361) - so `crystal.track.id` is the
   *     station's own answer to "which record is this about", and the whole
   *     library can be indexed by track id from ONE 31 kB fetch. The
   *     crystal is a real DSP reading: bpm, meter, bars, key with a
   *     confidence, the chord walk, the instrument roles, the demucs stems,
   *     the drum hit counts and the note census.
   *
   *     THE COVERAGE IS THE HEADLINE, AND IT IS SMALL. Measured: 22
   *     crystals against a library of 35,982 records, 18 of them on the
   *     `songsight` shelf. NONE of the 22 records in the live queue, the
   *     just-played and the record on air had one. So the honest default
   *     for this section is "no analysis has been done for this track yet",
   *     said plainly and with the coverage beside it, because an operator
   *     who sees an empty box on twenty records in a row has to be able to
   *     tell "nothing built" from "broken".
   *
   *  2. WHAT THE PAIR HAVE SAID ABOUT IT is the track library, #1061.
   *     /api/track-reads (app.py:99955) answers with one row per record
   *     that has a read on file - `intro`, `outro` and `ad` sides, each
   *     with the words and an `aired` count. Keyed by track id, 112 kB,
   *     one fetch. Measured: 558 records hold a read, 83 of the last 300
   *     spins have one (28%).
   *
   *     TWO TRAPS IN THAT ROUTE, BOTH OF WHICH MAKE IT LIE QUIETLY.
   *     track_reads_state (app.py:31060) serves `rows[:300]` of the 558 it
   *     holds, favourites first and then by recency - so a read on an old
   *     record EXISTS and is not served, and "no read" from this index is
   *     never proof. And it truncates every side to 200 characters
   *     (app.py:31046), so what is shown is the head of the read, not the
   *     read. Both are said on screen rather than hidden.
   *
   *  3. WHAT IS QUEUED FOR THE HOST TO SAY NEXT is _TRACK_TALK, the
   *     ten-deep record lookahead (#869, app.py:30719). track_talk_state
   *     (app.py:31553) hands back the next N records with `intro`/`outro`
   *     as "ready"/"written"/"" and the text of each.
   *
   *     IT HAS NO LIGHT DOOR. That state is served in exactly two places -
   *     /api/dj/pending (app.py:103138) and the pipeline state
   *     (app.py:41755) - and both are enormous: /api/dj/pending measured
   *     773,386 bytes and 2.0 s, because it carries the whole written
   *     reserve with script_plain and script_tinted at 12,000 characters a
   *     row. There is no parameter that trims it (`?full=1` only makes it
   *     bigger). So this view NEVER fetches it on a tap. It is behind one
   *     explicit press that reads it ONCE for the whole session and fills
   *     the prepared-talk section of every queued record at once - one
   *     operator gesture, one request, no timer.
   *
   *  4. THE RESEARCH IS REAL AND IS NOT SERVED. track_notes
   *     (app.py:54703) does a live web search per record and caches the
   *     reception note, the query it asked, the five source snippets it
   *     read, the model, the milliseconds and any dictionary sense of the
   *     title, in data/track_notes.json. Measured on disk: 400 records
   *     researched, 87 with a note worth saying, 13 with a dictionary
   *     sense, all 400 carrying their query and their sources.
   *
   *     NOT ONE ROUTE SERVES THAT CACHE. The only door is
   *     /api/music/notes/{id} (app.py:96074), which returns the note TEXT
   *     ALONE - no query, no sources, no model - and which, on a record
   *     that has never been looked up, performs the web search and the
   *     model call there and then. Tapping a row must not commission a
   *     model visit on the station's bottleneck, so this view does not call
   *     it automatically: the section says what the cache holds and what
   *     the only door costs, and the operator decides. The query and the
   *     sources are, today, unreachable from any client. That is a finding,
   *     not an omission here.
   *
   *  WHAT WAS LOOKED AT AND REJECTED. /api/screenplay/{hour} carries
   *  `round: "track_talk"` elements - measured 251 kB an hour, nine such
   *  elements in 09:00 - but the scene element names no track id and the
   *  dialogue under it names none either, so an hour of script cannot be
   *  tied to a record except by matching the title out of the text. And
   *  /api/dj/provenance/{line_id} (app.py:95598) is the route that really
   *  does carry the vector searches and the source documents with their
   *  quoted flags - but it is per LINE, not per record, it 404s for any
   *  line no longer in the booth's 240-row ring, and `track_id` appears on
   *  it only for song_analysis rows. Neither is a per-track store.
   *
   * Everything below is arithmetic over payloads: no DOM, no fetch, no
   * clock of its own, so the whole shape of a detail panel is testable
   * from node.
   */

  /* app.py:31047 - the three sides a record's read can hold. `ad` is the
   * #1061 case the operator asked for by name: an advert built around a
   * song, kept and played before that song comes round again. */
  const TRACK_READ_PARTS = [
    ["intro", "the intro"],
    ["outro", "the send-off"],
    ["ad", "the advert built on it"]
  ];

  /* app.py:31046 - track_reads_state truncates every side to 200 chars. */
  const TRACK_READ_CLIP = 200;

  function idOf(row) {
    return String((row || {}).id || "");
  }

  /* ONE FETCH, ONE INDEX. Each of these turns a whole-library payload into
   * a map by track id, so a tap on any row is a lookup and not a request.
   * That is the single-poller rule expressed as a data shape: the station
   * is asked about the LIBRARY once, never about a record. */

  function crystalIndex(payload) {
    const rows = Array.isArray((payload || {}).crystals) ? payload.crystals : [];
    const out = {};
    for (const crystal of rows) {
      /* crystal_with_track resolves the record by the analysed file's stem
       * first and a title search second (app.py:93372). A crystal whose
       * record could not be resolved has no `track` at all, and indexing it
       * under "" would hand it to every row with a blank id. */
      const id = idOf((crystal || {}).track);
      if (!id || out[id]) continue;
      out[id] = crystal;
    }
    return out;
  }

  function crystalFacts(crystal) {
    const c = crystal || {};
    const facts = [];
    const add = (label, value) => {
      const text = String(value == null ? "" : value).trim();
      if (text) facts.push({label, value: text});
    };

    const bpm = Number(c.bpm || 0);
    add("tempo", [bpm ? bpm.toFixed(1) + " BPM" : "",
      String(c.meter || ""),
      Number(c.bars || 0) ? c.bars + " bars" : ""].filter(Boolean).join(" · "));

    /* The confidence rides WITH the key rather than beside it. Measured
     * across the 22 crystals it runs from 0.39 to 0.58 - these are
     * estimates, and a key printed bare reads as a fact. */
    const sure = Number(c.key_confidence || 0);
    add("key", c.key
      ? String(c.key) + (sure ? " (" + Math.round(sure * 100) + "% sure)" : "")
      : "");

    const roles = c.instruments && typeof c.instruments === "object"
      ? c.instruments : {};
    const heard = [];
    for (const role of Object.keys(roles)) {
      const named = String(roles[role] || "").trim();
      if (named && heard.indexOf(named) < 0) heard.push(named);
    }
    add("instruments", heard.join(" · "));

    const stems = Array.isArray(c.stems) ? c.stems : [];
    add("stems", stems.length
      ? stems.length + ": " + stems.join(", ") : "");

    const drums = c.drums && typeof c.drums === "object" ? c.drums : {};
    const hits = Object.keys(drums)
      .map((name) => ({name, n: Number(drums[name] || 0)}))
      .filter((row) => row.n > 0)
      .sort((a, b) => b.n - a.n)
      .map((row) => row.n + " " + row.name.replace(/_/g, " "));
    add("drum hits", hits.join(" · "));

    const notes = c.notes && typeof c.notes === "object" ? c.notes : {};
    const count = Number(notes.count || 0);
    add("notes", count
      ? count + " notes"
        + (notes.lowest && notes.highest
          ? ", " + notes.lowest + " to " + notes.highest : "")
      : "");

    add("changes", Number(c.chord_count || 0)
      ? c.chord_count + " chord changes" : "");
    add("built", [String(c.built || ""),
      String(c.separation_model || "")].filter(Boolean).join(" · "));
    return facts;
  }

  /* The chord walk is a long line rather than a fact: it wraps, and
   * squeezing it into a label/value pair truncates the only part of a
   * crystal that reads like music. */
  function crystalChords(crystal) {
    return String((crystal || {}).chords || "").trim();
  }

  function readsIndex(payload) {
    const rows = Array.isArray((payload || {}).rows) ? payload.rows : [];
    const out = {};
    for (const row of rows) {
      const id = idOf(row);
      if (id && !out[id]) out[id] = row;
    }
    return out;
  }

  /* The sides of one record's read, in the order a show uses them. `aired`
   * is the count track_read_keep increments every time the words are taken
   * (app.py:30965), so it is how many times this exact read has gone out -
   * which is also the answer to "what have they said about this before". */
  function readLines(row) {
    const parts = (row || {}).parts || {};
    const out = [];
    for (const [key, label] of TRACK_READ_PARTS) {
      const side = parts[key] || {};
      const text = String(side.text || "").trim();
      if (!text) continue;
      const aired = Math.max(0, Number(side.aired || 0));
      out.push({
        part: key, label, text, aired,
        /* app.py:31046 clips at 200. Anything at the clip is the HEAD of a
         * read and the panel must not imply it is the whole of one. */
        clipped: text.length >= TRACK_READ_CLIP,
        tail: aired > 1 ? "aired " + aired + "×"
          : aired === 1 ? "aired once" : "never aired"
      });
    }
    return out;
  }

  /* /api/music/played (app.py:103559) - newest first, with the vote. Folded
   * to one entry per record: how many times it came round inside the window
   * asked for, and when it last did. */
  function playedIndex(payload) {
    const rows = Array.isArray((payload || {}).played) ? payload.played : [];
    const out = {};
    for (const row of rows) {
      const id = idOf(row);
      if (!id) continue;
      const at = Math.max(0, Number((row || {}).at || 0));
      const seat = out[id] || (out[id] = {
        id, spins: 0, last: 0, first: 0,
        vote: Math.max(-1, Math.min(1, Number((row || {}).vote || 0)))
      });
      seat.spins += 1;
      if (at > seat.last) seat.last = at;
      if (at && (!seat.first || at < seat.first)) seat.first = at;
    }
    return out;
  }

  /* track_talk_state's `tracks` (app.py:31560), off /api/dj/pending. The
   * big read - see the header. `intro`/`outro` are "ready" (the words AND
   * the recording are in hand), "written" (the words only) or "". */
  function lookaheadIndex(payload) {
    const block = (payload || {}).lookahead || {};
    const rows = Array.isArray(block.tracks) ? block.tracks : [];
    const out = {};
    for (const row of rows) {
      const id = idOf(row);
      if (id && !out[id]) out[id] = row;
    }
    return out;
  }

  function lookaheadLines(row) {
    const out = [];
    for (const [key, label] of [["intro", "the intro"],
      ["outro", "the send-off"]]) {
      const text = String((row || {})[key + "_text"] || "").trim();
      const state = String((row || {})[key] || "");
      if (!text && !state) continue;
      out.push({
        part: key, label, text, state,
        tail: state === "ready" ? "written and recorded"
          : state === "written" ? "written, not yet recorded" : ""
      });
    }
    return out;
  }

  /* /api/music/track/{id} (app.py:110210) - 824 bytes, the only per-record
   * fetch this view makes. Index metadata, the raw tag sheet and how much
   * of that artist and album the library holds. */
  function metaFacts(meta) {
    const m = meta || {};
    const tags = m.tags && typeof m.tags === "object" ? m.tags : {};
    const stats = m.stats && typeof m.stats === "object" ? m.stats : {};
    const facts = [];
    const add = (label, value) => {
      const text = String(value == null ? "" : value).trim();
      if (text) facts.push({label, value: text});
    };
    add("album", m.album);
    add("year", tags.TDRC || tags.date || tags["©day"] || tags.TYER);
    add("runs", Number(m.seconds || 0) ? clockText(m.seconds) : "");
    const rate = Number(tags.bitrate || 0);
    add("file", [String(m.ext || "").replace(".", "").toUpperCase(),
      rate ? Math.round(rate / 1000) + " kbps" : "",
      Number(m.size || 0) ? Math.round(Number(m.size) / 1048576) + " MB" : ""
    ].filter(Boolean).join(" · "));
    add("shelf", m.tape ? "one of the MX tapes" : m.station);
    add("this artist", Number(stats.artist_tracks || 0)
      ? stats.artist_tracks + " tracks on "
        + (Number(stats.artist_albums || 0) || 1) + " albums here" : "");
    add("this album", Number(stats.album_tracks || 0)
      ? stats.album_tracks + " tracks here" : "");
    const comment = String(tags["COMM::eng"] || tags.COMM || "").trim();
    add("tagged", comment.length > 120 ? comment.slice(0, 120) + "…" : comment);
    return facts;
  }

  /* WHAT ONE EXPANDED ROW SAYS, AS DATA.
   *
   * Every section reports one of three states and never a fourth:
   *
   *   facts/lines   there is something, here it is
   *   empty         there is nothing, and here is the sentence that says
   *                 so in words - "no analysis has been done for this
   *                 track yet", not an empty box
   *   pending       nobody has asked the station for this yet, and asking
   *                 costs something the operator should choose to spend
   *
   * The third state is the one that matters. Two of the five stores are
   * expensive to open - the writers' board is 773 kB and the research door
   * commissions a live web search and a model call - and a panel that
   * either opened them silently or pretended they did not exist would be
   * lying in one direction or the other.
   */
  function trackDetail(have) {
    const got = have || {};
    const sections = [];
    const push = (section) => { sections.push(section); return section; };

    /* ---- the record itself */
    const facts = metaFacts(got.meta);
    push(facts.length
      ? {key: "record", title: "The record", facts}
      : {key: "record", title: "The record",
        /* Undefined means the fetch is still out; null means it came back
         * with nothing OR 404ed, and /api/music/track cannot tell those
         * two apart from here, so the sentence covers both rather than
         * picking one and being wrong half the time. */
        empty: got.meta === undefined
          ? "reading the library…"
          : "the library did not answer with a record under this id"});

    /* ---- the analysis */
    const crystal = got.crystal || null;
    if (crystal) {
      push({key: "analysis", title: "What the station has analysed",
        facts: crystalFacts(crystal),
        lines: crystalChords(crystal)
          ? [{label: "chords", text: crystalChords(crystal), tail: ""}] : [],
        note: "SongSight, built " + String(crystal.built || "?")});
    } else {
      const built = Math.max(0, Number(got.crystalsBuilt || 0));
      const held = Math.max(0, Number(got.libraryTotal || 0));
      push({key: "analysis", title: "What the station has analysed",
        empty: "no analysis has been done for this track yet",
        note: built
          ? "SongSight has built " + built + " crystals"
            + (held ? " against " + held + " records in the library" : "")
          : ""});
    }

    /* ---- what has already been said about it */
    const said = readLines(got.read);
    if (said.length) {
      push({key: "said", title: "What the pair have said about it",
        lines: said,
        note: said.some((line) => line.clipped)
          ? "the station serves the first 200 characters of a read"
          : ""});
    } else {
      push({key: "said", title: "What the pair have said about it",
        empty: "nothing has been said about this record on air yet",
        /* app.py:31060 - 300 of 558 rows are served. Saying "nothing" about
         * a record whose read simply fell past that cap would be the exact
         * kind of quiet lie this panel exists to avoid. */
        note: got.readsServed && got.readsHeld
          && got.readsServed < got.readsHeld
          ? "the station serves " + got.readsServed + " of "
            + got.readsHeld + " records with a read, newest first - an "
            + "older one can exist and not be listed"
          : ""});
    }

    /* ---- what is queued for the host to say next */
    if (got.board === undefined) {
      push({key: "prepared", title: "What is queued for the host to say",
        pending: "the writers' board has not been read this session",
        note: "it arrives only inside /api/dj/pending - 773 kB, one read "
          + "for every record at once"});
    } else if (!got.board) {
      push({key: "prepared", title: "What is queued for the host to say",
        empty: "this record is not in the writers' lookahead"
          + (got.boardAhead ? " (the next " + got.boardAhead + ")" : "")});
    } else {
      const lines = lookaheadLines(got.board).filter((line) => line.text);
      push(lines.length
        ? {key: "prepared", title: "What is queued for the host to say",
          lines}
        : {key: "prepared", title: "What is queued for the host to say",
          empty: "this record is in the writers' lookahead with nothing "
            + "written for it yet"});
    }

    /* ---- on air before */
    const spun = got.history || null;
    if (spun && spun.spins) {
      const rows = [{label: "spins", value: spun.spins
        + (got.historyWindow
          ? " in the last " + got.historyWindow + " records played" : "")}];
      if (spun.last) {
        rows.push({label: "last on", value: agoText(spun.last, got.at)});
      }
      if (spun.vote) {
        rows.push({label: "your vote",
          value: spun.vote > 0 ? "up" : "down"});
      }
      push({key: "history", title: "On air", facts: rows});
    } else {
      push({key: "history", title: "On air",
        empty: got.historyWindow
          ? "this record has not come round in the last "
            + got.historyWindow + " played"
          : "no play history has been read"});
    }

    /* ---- the research */
    if (got.research === undefined) {
      push({key: "research", title: "What was looked up online",
        pending: "the station's research cache is not served to clients",
        note: "the only route (/api/music/notes) returns the note alone - "
          + "no query, no sources - and on a record never looked up it "
          + "runs the web search and the model call there and then"});
    } else if (got.research && String(got.research.notes || "").trim()) {
      push({key: "research", title: "What was looked up online",
        lines: [{label: "how it lands", tail: "",
          text: String(got.research.notes).trim()}]});
    } else {
      push({key: "research", title: "What was looked up online",
        empty: "the station has nothing on file about how this record "
          + "lands with people",
        /* 87 of 400 researched records carried a note. An empty answer from
         * that route genuinely cannot be told from a fresh search that came
         * back with nothing, and pretending otherwise would be a guess. */
        note: "87 of the 400 records it has looked up came back with "
          + "something worth saying"});
    }

    return {id: String(got.id || ""), sections};
  }

  /* ------------------------------------------------------------ formatting */

  function clockText(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  /* The wall clock on a lean-back screen is read from across a room, so
   * it is hours and minutes only - a ticking seconds field is movement
   * that means nothing at that distance. It is drawn off the STATION's
   * clock, not this machine's, so two terminals never disagree. */
  function wallClock(correctedAt) {
    const when = new Date(Number(correctedAt) || Date.now());
    const h = when.getHours();
    const m = when.getMinutes();
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function agoText(stampSeconds, at) {
    const stamp = Number(stampSeconds) || 0;
    if (!stamp) return "";
    const gap = Math.max(0, (Number(at) || Date.now()) / 1000 - stamp);
    if (gap < 90) return Math.round(gap) + "s ago";
    if (gap < 5400) return Math.round(gap / 60) + " min ago";
    if (gap < 172800) return Math.round(gap / 3600) + " h ago";
    return Math.round(gap / 86400) + " days ago";
  }

  const api = {
    MEDIA_WINDOW_S, FADE_S, TRACK_READ_PARTS, TRACK_READ_CLIP,
    skewOf, playhead, nowPlaying, whatsNext,
    queueRows, playedRows, trackRow,
    shelfRows, shelfTotal, requestRows, scheduleRows, galleryStills,
    firstFreePad, grabTarget, mediaStale,
    sleepPlan, sleepTick,
    crystalIndex, crystalFacts, crystalChords, readsIndex, readLines,
    playedIndex, lookaheadIndex, lookaheadLines, metaFacts, trackDetail,
    clockText, wallClock, agoText
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PineListenModel = api;
})(typeof window !== "undefined" ? window : globalThis);
