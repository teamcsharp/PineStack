/* TAKE MEDIA OFF THE STARVED SOCKET POOL.
 *
 * MEASURED ON THE TABLET, and this is the whole reason the file exists.
 * The station said the tablet should be sounding - routes all `here`, FM
 * on, and the tablet holding the air (#1008) - and the page agreed: the
 * music element was unpaused, unmuted, at full volume, not gagged. It was
 * simply receiving nothing:
 *
 *   musicPlayer     readyState 0  networkState 2 (LOADING)  buffered 0
 *   djVoiceAudio1   readyState 0  networkState 2 (LOADING)  buffered 0
 *   <video blob:>   readyState 4  currentTime advancing      <- fine
 *
 * Blob-backed video played perfectly; everything fetched over HTTP got zero
 * bytes. A CDP capture said why:
 *
 *   38 requests in flight to 10.89.1.246:8096, many 5-8s old
 *   a plain fetch of the stalled music url: 206, 65536 bytes, 46,171 ms
 *
 * The request was never failing. It was QUEUED. HTTP/1.1 allows six
 * connections per origin, the panel keeps dozens of polls outstanding, and
 * media waited three quarters of a minute behind them - by which time the
 * element had nothing to play and the tablet was silent.
 *
 * THE SECOND ORIGIN WAS TRIED, AND IT SILENCED THE TABLET. Moving media to
 * :8097 - the station's public door, which serves the same bytes faster -
 * gave each media request its own pool of six connections. It also stopped
 * any sound coming out at all, and that took a long time to find because
 * every indicator kept saying the audio was playing.
 *
 * The A/B, two fresh elements on the same track differing only in the port:
 *
 *   :8096   1 Tracks of which 1 are active   - audible
 *   :8097   0 active tracks                  - silent, clock still advancing
 *
 * Cross-origin media plays in this WebView and produces no output track for
 * it. So the port is left alone, and the queueing is dealt with where it
 * actually comes from - the panel's own oversized polls, /api/dj/pending cut
 * from 2,114 kB to 753 kB and /api/health/details (21.6s TTFB) backed off
 * from every 4s to every 30s.
 *
 * What remains here is the part that was worth having: asking for spoken
 * clips small.
 *
 * Scoped to media paths only. API calls stay on :8096, where the bearer and
 * the panel's own expectations live.
 */
(function () {
  'use strict';

  var MEDIA_PORT = '8096';   /* the page's own origin - see the header */
  /* Only paths that are audio or video bytes. An API route moved to the
   * other door would be a different and much worse bug. */
  var MEDIA_PATH = /^\/(music|media|generations\/image|api\/booth\/clip|api\/dj\/sfx-file)\b/;

  function reorigin(value) {
    if (typeof value !== 'string' || !value) return value;
    /* blob: and data: are already in hand - never touch them. */
    if (value.charAt(0) === 'b' || value.charAt(0) === 'd') {
      if (/^(blob|data):/.test(value)) return value;
    }
    try {
      var url = new URL(value, document.baseURI);
      if (url.hostname !== location.hostname) return value;
      /* NO EARLY RETURN ON THE PORT. It used to skip urls already on the
       * media port, which was right while that port differed from the
       * page's. Now that they are the same, that test matched everything
       * and silently skipped the one thing this file still does. */
      if (!MEDIA_PATH.test(url.pathname)) return value;
      /* THE PORT IS DELIBERATELY LEFT ALONE. See the header: moving media to
       * :8097 silenced the tablet completely. */
      /* ASK FOR THE SMALL VERSION OF SPOKEN CLIPS.
       *
       * MEASURED: one DJ line is a 3,610 kB uncompressed WAV, and fetching
       * it took 7,165 / 16,153 / 37,952 ms on three consecutive tries over a
       * 390 Mbit/s link - so the line was due long before its bytes arrived
       * and was simply missed. The tablet played music perfectly and the
       * DJs not at all:
       *
       *     musicPlayer     playing 100%   stalled  0%
       *     djVoiceAudio0   playing  18%   stalled 21%
       *     djVoiceAudio1   playing   9%   stalled 23%
       *
       * The station already solves this: #999's `br` serves an mp3
       * derivative of a clip, falls back to the original on a miss, and
       * encodes it for next time - so a miss costs bytes, never delay. The
       * tablet simply was not asking. 64 is in LOW_RATES (32/48/64/96/128)
       * and is about sixty times smaller than the WAV for speech.
       *
       * Only spoken clips. /music is already mp3 and plays perfectly; the
       * gallery is video. Narrowing this to /media is why the whitelist of
       * paths above is worth having. */
      if (/^\/media\//.test(url.pathname) && !url.searchParams.has('br')) {
        url.searchParams.set('br', '64');
      }
      return url.href;
    } catch (err) {
      return value;
    }
  }

  var proto = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
  if (!proto) return;

  /* The src PROPERTY. */
  var desc = Object.getOwnPropertyDescriptor(proto, 'src');
  if (desc && desc.set) {
    Object.defineProperty(proto, 'src', {
      configurable: true,
      enumerable: desc.enumerable,
      get: function () { return desc.get.call(this); },
      set: function (value) { desc.set.call(this, reorigin(value)); }
    });
  }

  /* ...and setAttribute, which the panel also uses. Both doors or the
   * rewrite is a coin toss depending on which line ran. */
  var setAttribute = Element.prototype.setAttribute;
  proto.setAttribute = function (name, value) {
    if (String(name).toLowerCase() === 'src') {
      return setAttribute.call(this, name, reorigin(value));
    }
    return setAttribute.call(this, name, value);
  };

  /* A <source> child inside an <audio>/<video> is the third door. */
  var sourceProto = window.HTMLSourceElement && window.HTMLSourceElement.prototype;
  if (sourceProto) {
    var sdesc = Object.getOwnPropertyDescriptor(sourceProto, 'src');
    if (sdesc && sdesc.set) {
      Object.defineProperty(sourceProto, 'src', {
        configurable: true,
        enumerable: sdesc.enumerable,
        get: function () { return sdesc.get.call(this); },
        set: function (value) { sdesc.set.call(this, reorigin(value)); }
      });
    }
  }

  window.__pineMediaOrigin = {port: MEDIA_PORT, reorigin: reorigin};
})();
