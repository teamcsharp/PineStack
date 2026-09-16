/* #1222: THE LEVELS, IN ONE PLACE, ON EVERY TAB.
 *
 * "On the tablet, the volume of the DJs is coming in very low, despite me
 *  setting their volume to a hundred and sixty three percent. I need the volume
 *  of the DJs to be responsive to what I set the slider to because sometimes I
 *  need their dialogue and sometimes I don't need their dialogue and sometimes
 *  I need the music. I just need the ability to set these levels dynamically in
 *  the app on the tablet and they take place for the broadcast on the tablet."
 *
 * And: "on the tablet I need a slider for setting the volume of videos that
 * play."
 *
 * WHY 163% CAME OUT QUIET. There are TWO level systems on this page and they
 * multiply, and he could only ever see one of them at a time. Read off his
 * tablet while he was complaining:
 *
 *     sliders   djGainVoice=200%  djGainMusic=31%  duck=63%
 *     pineMixer voice=0.68  music=0.21  sfx=1  video=1
 *     elements  djVoiceAudio0=0.68  djVoiceAudio1=0.68
 *
 * He had set the gain to 200% and `pineMixer.voice` was quietly holding the
 * elements at 0.68. Music was worse: 0.31 x 0.21, about six percent of unity.
 * Neither number is wrong on its own; there was simply nowhere that showed
 * both, so turning one up could always be undone by the other.
 *
 * HOW THIS FIXES IT. One slider per stream, 0 to 600%, and it drives BOTH
 * systems the only way that is coherent:
 *
 *   below 100%  cut with pineMixer (an element volume, which cannot exceed 1)
 *   above 100%  hold pineMixer at 1 and boost with the gain node, which the
 *               panel already routes analyser -> gain -> speakers and which
 *               accepts up to 600%
 *
 * So the number on the slider is the number that reaches the speakers, which
 * is the whole of what he asked for.
 *
 * VIDEOS get their own slider, 0 to 100%, because `pineMixer.video` lands on a
 * real <video>.volume and that genuinely cannot go above 1. Saying 150% on a
 * control that saturates at 100% would be the same lie this file exists to
 * remove.
 *
 * It mounts its own button, the way #1218 taught: a surface that supplies its
 * own way in works wherever it is loaded, and on the tablet nothing else was
 * ever going to call it.
 */
(function (root) {
  'use strict';
  if (root.PineLevels) return;

  var BTN_SHUT = 'pineLevelsShut';
  var sheet = null, btnNode = null, beat = null;

  function el(tag, cls, text) {
    var n = root.document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== null && typeof text !== 'undefined') n.textContent = String(text);
    return n;
  }

  /* The panel owns both systems. On the desk the SHELL owns every element's
     volume (#1147) and defines its own window.pineMixer, so this reads
     whatever is actually there rather than assuming which document it is in. */
  function mixer() {
    try {
      if (root.pineMixer && typeof root.pineMixer.get === 'function') {
        return root.pineMixer.get();
      }
    } catch (err) { /* fall through */ }
    return {voice: 1, music: 1, sfx: 1, video: 1};
  }

  function gainEl(which) {
    return root.document.getElementById(
      which === 'music' ? 'djGainMusic' : 'djGainVoice');
  }

  /* What the speakers are actually getting, as a percentage, whichever half
     of the arrangement is carrying it. */
  function levelOf(which) {
    var m = mixer();
    var cut = which === 'music' ? m.music : m.voice;
    var g = gainEl(which);
    var boost = g ? Number(g.value) : 100;
    if (cut < 0.999) return Math.round(cut * 100);
    return Math.round(boost);
  }

  function setLevel(which, pct) {
    var want = Math.max(0, Math.min(600, Number(pct) || 0));
    var m = {};
    if (want <= 100) {
      m[which] = want / 100;
      try { if (root.pineMixer) root.pineMixer.set(m); } catch (err) { /* private mode */ }
      apply(which, 100);
    } else {
      m[which] = 1;
      try { if (root.pineMixer) root.pineMixer.set(m); } catch (err) { /* private mode */ }
      apply(which, want);
    }
  }

  /* The gain slider is the panel's own control, so it is moved the way a
     person would move it - value then 'input' - and the panel's existing
     handler does the rest. Nothing here reaches into the audio graph itself. */
  function apply(which, pct) {
    var g = gainEl(which);
    if (!g) return;
    g.value = String(Math.max(0, Math.min(600, pct)));
    try { g.dispatchEvent(new root.Event('input', {bubbles: true})); }
    catch (err) {
      try { g.dispatchEvent(new root.Event('input')); } catch (e2) { /* old host */ }
    }
  }

  function setVideo(pct) {
    var want = Math.max(0, Math.min(100, Number(pct) || 0));
    try { if (root.pineMixer) root.pineMixer.set({video: want / 100}); }
    catch (err) { /* private mode */ }
  }

  function videoLevel() { return Math.round((mixer().video) * 100); }

  function row(host, key, label, most, read, write, hint) {
    var wrap = el('div', 'plv-row');
    var head = el('div', 'plv-head');
    head.appendChild(el('span', 'plv-name', label));
    var val = el('span', 'plv-val', read() + '%');
    head.appendChild(val);
    wrap.appendChild(head);
    var slide = el('input', 'plv-slide');
    slide.type = 'range';
    slide.min = '0';
    slide.max = String(most);
    slide.step = '1';
    slide.value = String(read());
    slide.setAttribute('aria-label', label);
    slide.addEventListener('input', function () {
      val.textContent = slide.value + '%';
      write(slide.value);
    });
    wrap.appendChild(slide);
    if (hint) wrap.appendChild(el('div', 'plv-hint', hint));
    host.appendChild(wrap);
    return function refresh() {
      if (root.document.activeElement === slide) return;   /* not under him */
      var now = read();
      if (String(now) !== slide.value) {
        slide.value = String(now);
        val.textContent = now + '%';
      }
    };
  }

  function open() {
    if (sheet) return sheet;
    var node = el('div', 'plv-sheet');
    var head = el('div', 'plv-title');
    head.appendChild(el('span', 'plv-title-t', 'Levels on this terminal'));
    var shut = el('button', 'plv-x', 'x');
    shut.setAttribute('type', 'button');
    shut.setAttribute('aria-label', 'Close the levels');
    shut.addEventListener('click', close);
    head.appendChild(shut);
    node.appendChild(head);

    var refreshers = [];
    refreshers.push(row(node, 'voice', 'The DJs', 600,
      function () { return levelOf('voice'); },
      function (v) { setLevel('voice', v); },
      'Above 100% is a real boost, not a cap.'));
    refreshers.push(row(node, 'music', 'The music', 600,
      function () { return levelOf('music'); },
      function (v) { setLevel('music', v); }));
    refreshers.push(row(node, 'video', 'Videos', 100,
      videoLevel, setVideo,
      'A video cannot play louder than itself, so this one stops at 100%.'));

    node.appendChild(el('div', 'plv-foot',
      'This terminal only. The station keeps its own levels; these sit on top '
      + 'and take effect as you drag.'));

    root.document.body.appendChild(node);
    sheet = node;
    /* Follow the panel's own sliders if they are moved elsewhere, but never
       while he has hold of one of these. */
    beat = root.setInterval(function () {
      if (!sheet) return;
      for (var i = 0; i < refreshers.length; i += 1) refreshers[i]();
    }, 1500);
    try { if (beat && typeof beat.unref === 'function') beat.unref(); }
    catch (err) { /* a browser timer */ }
    return node;
  }

  function close() {
    if (beat) { try { root.clearInterval(beat); } catch (err) { /* gone */ } beat = null; }
    if (sheet && sheet.parentNode) sheet.parentNode.removeChild(sheet);
    sheet = null;
  }

  function toggle() { return sheet ? (close(), null) : open(); }

  /* --------------------------------------------------------------- the way in */

  function button() {
    if (btnNode && root.document.body && root.document.body.contains(btnNode)) {
      return btnNode;
    }
    btnNode = null;
    try {
      if (root.localStorage.getItem(BTN_SHUT) === '1') return null;
    } catch (err) { /* no storage: show it */ }
    if (!root.document || !root.document.body) return null;
    var b = el('button', 'plv-dot', 'LVL');
    b.id = 'pineLevelsDot';
    b.setAttribute('type', 'button');
    b.setAttribute('title', 'Levels on this terminal - DJs, music, videos');
    b.setAttribute('aria-label', 'Levels');
    b.addEventListener('click', function (ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      toggle();
    });
    root.document.body.appendChild(b);
    btnNode = b;
    return b;
  }

  function plant() {
    try { button(); } catch (err) { /* a missing button never costs the view */ }
  }

  root.PineLevels = {
    open: open, close: close, toggle: toggle, button: button,
    level: levelOf, set: setLevel, video: videoLevel, setVideo: setVideo
  };

  try {
    if (root.document && root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', plant);
    } else { plant(); }
    var keep = root.setInterval(plant, 4000);
    try { if (keep && typeof keep.unref === 'function') keep.unref(); }
    catch (err) { /* a browser timer */ }
  } catch (err) { /* older host: PineLevels.button() still works by hand */ }
})(typeof window !== 'undefined' ? window : globalThis);
