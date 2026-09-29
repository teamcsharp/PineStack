  /* ================================================== [plquiet] the silence sliders
   * The thin row under the header: how long the set may stay silent before
   * the DJ gets the music back (settings.silence_seconds), and how much
   * silence makes the album recorder start a new track (settings.split_seconds).
   * Both are the station's settings (remembered, read live - no restart), and
   * a "silent N s" readout counts toward each while the input is quiet. */
  var QUIET = {
    handoff: {key: 'silence_seconds', min: 10, max: 180, def: 45},
    split: {key: 'split_seconds', min: 5, max: 120, def: 15}
  };

  function quietSecs(key) {
    var spec = key === 'split_seconds' ? QUIET.split : QUIET.handoff;
    var v = num(model.settings && model.settings[key]);
    if (!isFinite(v)) {
      var q = model.state && model.state.quiet;
      v = num(q && (key === 'split_seconds' ? q.split_s : q.handoff_s));
    }
    if (!isFinite(v)) v = spec.def;
    return Math.round(Math.max(spec.min, Math.min(spec.max, v)));
  }

  function quietSlider(box, spec, lead, tip) {
    var wrap = make('label', 'pl-quiet-one');
    wrap.title = tip;
    wrap.appendChild(make('span', 'pl-quiet-lead', lead));
    var input = guard(make('input'));
    input.type = 'range';
    input.min = String(spec.min); input.max = String(spec.max); input.step = '1';
    input.value = String(spec.def);
    input.setAttribute('aria-label', lead + ' this many seconds of silence');
    var out = make('output', 'pl-quiet-out', spec.def + ' s');
    wrap.appendChild(input);
    wrap.appendChild(out);
    wrap.appendChild(make('span', 'pl-quiet-tail', 'of silence'));
    box.appendChild(wrap);
    return {root: wrap, input: input, out: out, spec: spec};
  }

  /* A new track has to come before the hand-back (past it the DJ already has
   * the air), so the split stays under the hand-back; the station clamps the
   * same way, this only says so at once. */
  function quietPick(which, v, final) {
    var q = ui.quiet;
    var spec = QUIET[which];
    v = Math.round(Math.max(spec.min, Math.min(spec.max, Number(v))));
    var capped = false;
    if (which === 'split') {
      var hand = quietSecs('silence_seconds');
      if (v >= hand) { v = Math.max(QUIET.split.min, hand - 1); capped = true; }
    }
    setText(q[which].out, v + ' s');
    setClass(q[which].root, 'capped', capped);
    if (!final) return;
    q[which].input.value = String(v);
    if (!model.settings) model.settings = {};
    model.settings[spec.key] = v;
    var note = '';
    if (which === 'handoff' && quietSecs('split_seconds') >= v) {
      model.settings.split_seconds = Math.max(QUIET.split.min, v - 1);
      note = 'Saved. The new-track split follows the hand-back down to ' + model.settings.split_seconds + ' s - a track has to close before the DJ takes over.';
    } else if (capped) {
      note = 'Saved. A new track has to come before the hand-back (' + quietSecs('silence_seconds') + ' s), so the split stops at ' + v + ' s.';
    }
    var body = {};
    body[spec.key] = v;
    act('/api/pinelive/settings', body).then(function (ans) {
      if (note && ans && ans.ok !== false) say(note, '');
    });
    paintQuiet();
  }

  function buildQuiet() {
    var box = make('div', 'pl-quiet');
    var q = ui.quiet = {box: box};
    q.handoff = quietSlider(box, QUIET.handoff, 'Hand back to the DJ after',
      'How long the set may stay silent before the station hands the music back to the DJ (default 45 s, 10-180 s). '
      + 'Sound before then keeps the set on the air; once the DJ has it, the set takes the air back as soon as you play again. '
      + 'A cable or sender that stops arriving at all still hands back at once (Event: "No frames for"). '
      + 'The new-track split below always comes first, so it is kept shorter than this.');
    q.split = quietSlider(box, QUIET.split, 'New album track after',
      'With Album recording on: silence longer than this closes the running track, and the next sound starts the next numbered track (default 15 s, 5-120 s). '
      + 'Shorter silences stay inside the track. The closed track keeps 2 s of the silence as its ring-out and the rest is cut; the new one opens half a second before the sound. '
      + 'It must be shorter than the hand-back above - past the hand-back the DJ already has the air - so it stops just under it.');
    q.handoff.input.addEventListener('input', function () { quietPick('handoff', q.handoff.input.value, false); });
    q.handoff.input.addEventListener('change', function () { quietPick('handoff', q.handoff.input.value, true); });
    q.split.input.addEventListener('input', function () { quietPick('split', q.split.input.value, false); });
    q.split.input.addEventListener('change', function () { quietPick('split', q.split.input.value, true); });
    q.now = make('span', 'pl-quiet-now');
    q.now.setAttribute('role', 'timer');
    q.now.title = 'How long the input has been silent, and what happens next';
    q.now.appendChild(iconNode('c:time'));
    q.nowWords = make('span', '', '');
    q.now.appendChild(q.nowWords);
    q.now.hidden = true;
    box.appendChild(q.now);
    return box;
  }

  function quietReadout(st) {
    if (!st || !st.armed) return '';
    var q = st.quiet || {};
    var f = st.failover || {};
    var silent = num(q.silent_s);
    if (!isFinite(silent)) silent = num(f.quiet_s);
    if (!isFinite(silent) || silent < 1) return '';
    var hand = quietSecs('silence_seconds'), split = quietSecs('split_seconds');
    var parts = ['Silent ' + Math.floor(silent) + ' s'];
    var sp = st.recording && st.recording.split;
    var album = q.album !== undefined ? !!q.album : !!(st.recording && st.recording.on);
    if (album) {
      if (sp && sp.waiting) parts.push('track ' + Math.max(1, (sp.track || 2) - 1) + ' closed');
      else parts.push('new track in ' + Math.max(0, Math.ceil(split - silent)) + ' s');
    }
    if (st.phase === 'fallback') parts.push('the DJ has the music until you play');
    else parts.push('back to the DJ in ' + Math.max(0, Math.ceil(hand - silent)) + ' s');
    return parts.join(' · ');
  }

  function paintQuiet() {
    var q = ui.quiet;
    if (!q) return;
    ['handoff', 'split'].forEach(function (which) {
      var s = q[which];
      if (s.input.__editing) return;
      setClass(s.root, 'capped', false);
      var v = quietSecs(s.spec.key);
      if (String(s.input.value) !== String(v)) s.input.value = String(v);
      setText(s.out, v + ' s');
    });
    var st = model.state;
    var albumOff = !!(model.settings && model.settings.record === false);
    setClass(q.split.root, 'off', albumOff);
    var words = quietReadout(st);
    setText(q.nowWords, words);
    setHidden(q.now, !words);
    var silent = st && st.quiet ? num(st.quiet.silent_s) : NaN;
    setClass(q.now, 'near', isFinite(silent) && silent >= quietSecs('silence_seconds') * 0.67);
    setClass(q.now, 'gone', !!(st && st.phase === 'fallback'));
  }

