/* THE CLIP DOCTOR - why the video button gave you nothing, and the three
 * things you can press about it.
 *
 * "When I tap the video clip icon on pinetab, if it's unable to find a
 *  clip, then allow me to troubleshoot via popup and tap options to
 *  rebuild the connection and to ping the server and to query the
 *  folders."
 *
 * A miss on the video button has meant four different things this month,
 * and every one of them printed the same four words on the strip: "still
 * warming - tap again". The share had come adrift from the container
 * (#1361: /samples was the empty folder UNDERNEATH the mount); the index
 * thread had died silently; the library had been read and nothing in it
 * qualified; and once, the walk was simply still running. Only the last
 * one is cured by tapping again, and the operator had no way to tell it
 * from the other three.
 *
 * So a miss opens this instead. The station's own doctor (#1361) names the
 * fault AND the cure; this paints it and puts the cure under a thumb.
 *
 * It runs on both surfaces from one file. On the tablet the panel is served
 * by the station, so a bare path is right and the key is on the page; in
 * the Electron chrome the document is file://, so the bridge does the
 * talking. Same split every view here carries (#1348, #1360).
 */
(function (root) {
  'use strict';

  var box = null;
  var busy = false;

  function where() {
    try {
      if (root.location && /^https?:$/.test(root.location.protocol)) return '';
      if (root.pineStationBase) return root.pineStationBase();
    } catch (err) { /* fall through */ }
    return 'http://127.0.0.1:8096';
  }

  function key() {
    try { if (typeof root.SERVER_KEY === 'string') return root.SERVER_KEY; }
    catch (err) { /* not on this page */ }
    return '';
  }

  function get(path) {
    try {
      if (root.pineDesktop && root.pineDesktop.get) return root.pineDesktop.get(path);
    } catch (err) { /* fall through */ }
    var h = key() ? {Authorization: 'Bearer ' + key()} : {};
    return fetch(where() + path, {headers: h, cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; });
  }

  function post(path, body) {
    try {
      if (root.pineDesktop && root.pineDesktop.post) return root.pineDesktop.post(path, body || {});
    } catch (err) { /* fall through */ }
    var h = {'Content-Type': 'application/json'};
    if (key()) h.Authorization = 'Bearer ' + key();
    return fetch(where() + path, {method: 'POST', headers: h,
      body: JSON.stringify(body || {})})
      .then(function (r) { return r.ok ? r.json() : null; });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  /* ---------------------------------------------------------- furniture */

  function build() {
    if (box) return box;
    var back = el('div', 'cd-back');
    back.id = 'pineClipDoctor';
    box = el('div', 'cd-box');
    var bar = el('div', 'cd-bar');
    bar.appendChild(el('b', null, 'CLIP DOCTOR'));
    var x = el('button', 'cd-x', '×');
    x.type = 'button';
    x.title = 'Close';
    x.addEventListener('click', close);
    bar.appendChild(x);
    box.appendChild(bar);
    box.appendChild(el('div', 'cd-verdict'));
    box.appendChild(el('ol', 'cd-steps'));
    box.appendChild(el('div', 'cd-counts'));
    var row = el('div', 'cd-row');
    [
      ['rebuild', 'Rebuild', 'Throw every clip cache away and read the library into the book again'],
      ['ping', 'Ping the server', 'Is the sample share answering, and how fast'],
      ['folders', 'Query the folders', 'What is actually in each named clip folder'],
      ['try', 'Try a clip', 'Ask for a video clip right now']
    ].forEach(function (b) {
      var n = el('button', 'cd-btn', b[1]);
      n.type = 'button';
      n.title = b[2];
      n.setAttribute('data-act', b[0]);
      n.addEventListener('click', function (ev) { ev.stopPropagation(); act(b[0]); });
      row.appendChild(n);
    });
    box.appendChild(row);
    var out = el('pre', 'cd-out');
    out.hidden = true;
    box.appendChild(out);
    back.appendChild(box);
    /* Tap away and it closes - the one rule every sheet here follows. */
    back.addEventListener('click', function (ev) { if (ev.target === back) close(); });
    document.body.appendChild(back);
    return box;
  }

  function q(cls) { return box ? box.querySelector('.' + cls) : null; }

  function out(text) {
    var o = q('cd-out');
    if (!o) return;
    o.hidden = !text;
    o.textContent = String(text || '');
  }

  /* --------------------------------------------------------------- paint */

  function paint(d) {
    var v = q('cd-verdict');
    var s = q('cd-steps');
    var c = q('cd-counts');
    if (!v || !s || !c) return;
    if (!d) {
      v.textContent = 'the station did not answer';
      s.innerHTML = '';
      c.textContent = '';
      return;
    }
    v.textContent = String(d.verdict || '');
    v.classList.toggle('good', !d.cure);
    s.innerHTML = '';
    (d.steps || []).forEach(function (t) { s.appendChild(el('li', null, t)); });
    var book = d.book || {};
    var scan = d.book_scan || {};
    var share = d.share || {};
    var bits = [
      'book: ' + (book.video_playable || 0) + ' video ready of ' + (book.rows || 0) + ' rows'
        + (scan.running ? ' (writing: ' + (scan.folder || '') + ' ' + (scan.done || 0) + '/' + (scan.folders || 0) + ')' : ''),
      'share: ' + (share.present ? (share.entries || 0) + ' entries' : 'NOT MOUNTED')
        + (share.same_device_as_data ? ' - STALE BIND' : ''),
      'folders: ' + (d.folder_count || 0) + ' with ' + (d.files_seen || 0) + ' files',
      'lengths held: ' + (d.lengths_held || 0)
    ];
    if (scan.why) bits.push('last walk: ' + scan.why);
    c.textContent = bits.join('  ·  ');
    /* The cure the doctor named gets the accent, so the right button is
     * the obvious one and not one of four equals. */
    Array.prototype.forEach.call(box.querySelectorAll('.cd-btn'), function (b) {
      b.classList.toggle('cure', b.getAttribute('data-act') === String(d.cure || ''));
    });
  }

  function look() {
    return Promise.resolve(get('/api/sfx/doctor')).then(paint, function () { paint(null); });
  }

  /* ------------------------------------------------------------- actions */

  function act(which) {
    if (busy) return;
    busy = true;
    out('…');
    var done = function (text) { busy = false; out(text); look(); };
    if (which === 'try') {
      Promise.resolve(post('/api/sfx/video/cue', {who: 'doctor'})).then(function (got) {
        var clip = got && got.clip;
        if (clip) {
          try { if (root.PineSfxTv && root.PineSfxTv.cut) root.PineSfxTv.cut(clip); }
          catch (err) { /* it is in the ring either way */ }
          done('playing ' + String(clip.sting || 'a clip'));
          setTimeout(close, 900);
        } else {
          done(String((got && got.say) || 'no clip'));
        }
      }, function () { done('the station did not answer'); });
      return;
    }
    Promise.resolve(post('/api/sfx/doctor/' + which, {})).then(function (got) {
      if (!got) { done('the station did not answer'); return; }
      if (which === 'folders') {
        var lines = [String(got.say || '')];
        (got.folders || []).forEach(function (f) {
          lines.push('  ' + (f.files < 0 ? '  ?' : String(f.files).padStart(5))
            + '  ' + (f.video ? '(' + f.video + ' video) ' : '') + f.name
            + (f.why ? '  - ' + f.why : ''));
        });
        done(lines.join(String.fromCharCode(10)));
        return;
      }
      if (which === 'ping') {
        var t = [String(got.say || '')];
        if (got.read_file) t.push('read ' + got.read_file + ' in ' + got.read_ms + ' ms');
        if (got.read_why) t.push('file read failed: ' + got.read_why);
        done(t.join(String.fromCharCode(10)));
        return;
      }
      done(String(got.say || 'done'));
    }, function () { done('the station did not answer'); });
  }

  function open(reason) {
    build();
    var back = document.getElementById('pineClipDoctor');
    if (back) back.classList.add('show');
    out(reason ? String(reason) : '');
    look();
  }

  function close() {
    var back = document.getElementById('pineClipDoctor');
    if (back) back.classList.remove('show');
  }

  root.PineClipDoctor = {open: open, close: close, look: look};

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineClipDoctor;
  }
}(typeof window !== 'undefined' ? window : globalThis));
