(function (root) {
  function stationRows(station, now = Date.now()) {
    const rows = new Map();
    const absorb = (row, status = '') => {
      if (!row?.id || !row.text || /^(seen|tick|ping|heartbeat)$/.test(row.kind || '')) return;
      const previous = rows.get(String(row.id)) || {};
      const aired = row.aired || previous.aired;
      const audio = ['box', 'stream', 'both', 'airing'].includes(aired)
        || !!(row.audio_url || row.clip_url);
      const label = status || (aired === 'airing' ? 'Playing' : ['box', 'stream', 'both'].includes(aired) ? 'Aired'
        : aired === 'prepared' ? 'Recorded / waiting' : ['published', 'page'].includes(aired) ? 'Awaiting playback'
        : aired === 'failed' ? 'Audio failed' : 'Booth activity');
      rows.set(String(row.id), {...previous, ...row, id: String(row.id), lcdStatus: label, lcdAudio: audio});
    };
    for (const row of station.chat || []) absorb(row);
    const stream = station.stream_now;
    const offset = now / 1000 - Number(stream?.at || 0);
    let current;
    if (stream?.at && offset >= 0 && offset <= Number(stream.length || 0) + 4) {
      for (const row of stream.rows || []) {
        if (Number(row.from) <= offset && offset < Number(row.until)) {
          current = {...row, aired: 'airing', air_at: Number(stream.at) + Number(row.from)};
        }
      }
    }
    const live = current || station.speaking_now;
    if (live?.id && live.text) {
      const before = rows.get(String(live.id)) || {};
      rows.delete(String(live.id)); // the current speaker stays visible last
      absorb({...before, ...live, aired: 'airing'}, 'Playing');
    }
    return [...rows.values()];
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {stationRows};
  else root.PineLcdDialogue = {stationRows};
})(typeof window !== 'undefined' ? window : globalThis);
