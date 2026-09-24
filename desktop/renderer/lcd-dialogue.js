(function (root) {
  function stationRows(station, now = Date.now()) {
    const rows = new Map();
    const absorb = (row, status = '') => {
      /* A ROW WITH AUDIO AND NO WORDS IS STILL A THING YOU CAN SAMPLE.
       * This dropped anything textless, which is exactly the shape a sting
       * or an audio-only cue arrives in - invisible in the feed and so
       * impossible to drag onto a pad. Words OR audio is enough now. */
      const hasAudio = !!(row && (row.url || row.audio_url || row.clip_url
        || row.media || row.clip_media));
      if (!row?.id || (!row.text && !hasAudio)
        || /^(seen|tick|ping|heartbeat)$/.test(row.kind || '')) return;
      const previous = rows.get(String(row.id)) || {};
      const aired = row.aired || previous.aired;
      const audio = ['box', 'stream', 'both', 'airing'].includes(aired)
        || !!(row.audio_url || row.clip_url);
      const label = status || (['airing', 'box', 'stream', 'both'].includes(aired) ? 'Aired'
        : aired === 'prepared' ? 'Recorded / waiting' : ['published', 'page'].includes(aired) ? 'Awaiting playback'
        : aired === 'failed' ? 'Audio failed' : 'Booth activity');
      rows.set(String(row.id), {...previous, ...row, id: String(row.id), lcdStatus: label, lcdAudio: audio});
    };
    for (const row of station.chat || []) absorb(row);
    /* THE RECORDS, TOO.
     *
     * "Show everything in the feed, including clips that are played. I want
     *  to be able to put any audio that is played on the radio on the
     *  sampler, but I want to see it in the feed."
     *
     * `chat` is the BOOTH - what was said. A record turning is not a chat
     * row, so the music never appeared here at all and could not be dragged
     * onto a pad. `now` is what is turning, and it carries its own signed
     * url.
     *
     * ONE RECORD, AND ONLY THE ONE THAT IS PLAYING. This used to fold in
     * `played` as well - the last ten - and the feed came back with a
     * column of songs at the top before any dialogue. "I only need it to
     * show just the active playing song. I do not need it to show more than
     * one song in the feed." The history is not lost: the Music view lists
     * what has played and can put any of it on a pad.
     *
     * It is marked `kind: 'music'` rather than dressed up as a booth row,
     * because sourceFor has to be able to tell them apart: a record is taken
     * whole from its own file, not cut out of the booth ring. */
    const record = (track, status) => {
      if (!track || !track.url) return;
      const id = 'music:' + String(track.id || track.url);
      if (rows.has(id)) return;
      const artist = track.artist ? ' · ' + track.artist : '';
      rows.set(id, {
        id, kind: 'music', who: 'Record', name: track.artist || 'Record',
        text: (track.title || 'a record') + artist,
        url: track.url, seconds: Number(track.seconds) || 0,
        lcdStatus: status, lcdAudio: true, music: true
      });
    };

    /* THE RECORD GOES IN BEFORE THE LIVE SPEAKER, not after.
     *
     * The feed reverses this list to put the newest at the top, so whatever
     * is added LAST appears FIRST. Adding the record after the live speaker
     * therefore pushed the song above the line being spoken - which is how
     * the screenshot came to show a track title where the talking should be.
     * The thing currently being SAID is the latest thing playing; the record
     * is the bed under it and sits just below. */
    record(station.now, station.playing && !station.paused ? 'Playing' : 'Aired');

    const stream = station.stream_now;
    const offset = now / 1000 - Number(stream?.at || 0);
    let current;
    if (!station.paused && stream?.at && offset >= 0
        && offset < Number(stream.length || 0)) {
      for (const row of stream.rows || []) {
        if (Number(row.from) <= offset && offset < Number(row.until)) {
          current = {...row, aired: 'airing', air_at: Number(stream.at) + Number(row.from)};
        }
      }
    }
    const reported = station.paused || (stream?.at && !current
      && (stream.rows || []).some((row) => String(row.id) === String(station.speaking_now?.id)))
      ? null : station.speaking_now;
    /* stream_now is the accurate clock but its rows carry only id/from/until.
     * Merge the same-ID speaking report before falling back to chat so a
     * restart or a short chat ring can never erase words the station is
     * explicitly reporting as audible. */
    const live = current
      ? {...((reported && String(reported.id) === String(current.id)) ? reported : {}), ...current}
      : reported;
    if (live?.id) {
      const before = rows.get(String(live.id)) || {};
      /* [#1386] THE SPEAKING LINE STAYS WHERE THE SCRIPT PUT IT.
       *
       * "the script window is still jumping around the script unusually
       * instead of streaming as a stable feed with one line happening
       * after another sequentially... the goal of having the script
       * window being 1:1 and flowing logically."
       *
       * This Map iterates in INSERTION order, and the line that was
       * speaking used to be deleted and re-inserted so it would land at
       * the end of the list. That is what threw the reader around: the
       * active line leapt out of its place in the conversation, and every
       * line that had ALREADY been live stayed bunched at the tail in the
       * order it went live rather than the order it was written. A pane
       * asked to read downwards cannot, because the row it is following
       * keeps moving.
       *
       * A Map.set on a key that is already present keeps its original
       * position, so absorb() below now updates the row IN PLACE and the
       * list stays in the order the lines arrived - which for a script is
       * the order they are meant to be read. Nothing is lost: the row is
       * still marked `aired: airing` and labelled Playing, so any view
       * that wants to find the live line looks at the mark instead of at
       * the position. The ledger's own (block, ord) sort is measured
       * clean - 518 rows, 0 backward pairs - so the document was right
       * and only this one re-insertion was moving it.
       */
      /* A stream_now turn carries ONLY {id, from, until} - app.py:25295
       * serialises no text for it. So `current` never has any, the old
       * `live.text` guard failed, and absorb() (which drops a row with no
       * text) threw it away: on the coalesced road, which is most of the
       * show, nothing was ever marked Playing. The text is on the chat row
       * of the same id, so take it from there. */
      absorb({...before, ...live, text: live.text || before.text,
        aired: 'airing'}, 'Playing');
    }
    return [...rows.values()];
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {stationRows};
  else root.PineLcdDialogue = {stationRows};
})(typeof window !== 'undefined' ? window : globalThis);
