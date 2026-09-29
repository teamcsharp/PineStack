  /* ================================================== [camgrey] PineCam to live, offline */
  /* "grey this out if the camera's offline." The reading is the one this
   * popup already polls: /api/pinelive/state's picture block carries the
   * station's own pinelink_state() - cam_live (state "live" AND fresh, the
   * rule the Pine Cam box uses), cam_state, cam_why and how long ago it was
   * last live. No new poll. Greyed is not disabled: a flip still records the
   * preference and takes effect the moment the camera is back. Unknown (no
   * state yet) is never greyed on a guess. */
  var CAM_STATE_WORDS = {
    'no-link': 'the camera\'s Wi-Fi isn\'t on the air',
    'never-run': 'the camera link has never run on this station',
    'linked': 'the camera is joined but no picture is arriving',
    'joining': 'the camera link is still joining'
  };

  function camLink() {
    var pic = (model.state && model.state.picture) || null;
    if (!pic || pic.cam_live === undefined) return null;
    return {live: !!pic.cam_live, state: String(pic.cam_state || ''), why: String(pic.cam_why || ''),
      seenAgo: pic.cam_seen_ago == null ? NaN : num(pic.cam_seen_ago)};
  }

  function camOfflineWords(c) {
    var why = c.why || CAM_STATE_WORDS[c.state]
      || (c.state === 'live' ? 'its last picture is stale' : c.state ? 'the link says "' + c.state + '"' : 'the link is not live');
    return 'Pine Cam is offline - ' + why + (isFinite(c.seenAgo) ? ' (last seen ' + fmtAgo(c.seenAgo) + ')' : '')
      + '. The switch is kept and takes effect when it reconnects.';
  }

  /* grey `node` (and title `tipNode`) while the camera is not live; `base`
   * is the title it carries when the camera is fine */
  function paintCamGrey(node, tipNode, base) {
    if (!node) return;
    var c = camLink();
    var off = !!(c && !c.live);
    setClass(node, 'pl-cam-offline', off);
    var tip = off ? camOfflineWords(c) + (base ? '\n' + base : '') : (base || '');
    [node, tipNode].forEach(function (n) {
      if (n && n.title !== tip) n.title = tip;
    });
  }

  /* ================================================== [pinestream-choose] which screen */
  /* "grayed out and inert if the pine stream is off. But I do want to be
   * able to select which one I'm streaming whenever I enable the pine
   * stream." Off: both source buttons are inert, the last-used one marked
   * faintly. On: a small chooser anchored to the switch - two big buttons,
   * the last-used preselected and focused; a tap starts streaming that
   * screen. Its X, Escape, BACK or a tap beside it cancel, and PineStream
   * stays OFF: nothing streams without a choice, and nothing auto-starts.
   * No thumbnails: a picture of a screen that is not streaming would mean
   * capturing it while the switch is off. */
  var STREAM_OFF_TIP = 'PineStream is off - turn it on to choose a screen';

  function streamHere() {
    try { var s = root.PineStream && root.PineStream.state(); if (s && s.surface) return s.surface; } catch (err) { /* no agent */ }
    return httpPage() ? 'pinetab' : 'pineapp';
  }

  function chooserLabel(v) {
    var here = streamHere() === v;
    if (v === 'pineapp') return here ? 'Pine app (this desk)' : 'Pine app (the desk)';
    return here ? 'PineTab (this tablet)' : 'PineTab';
  }

  /** {ok, why} for a screen, from the station's check-ins (pinestream.js
   *  says it is there every few seconds; a missing or asleep one says so). */
  function streamSourceReady(v) {
    var src = (streamBlock().sources || {})[v];
    if (!src) return {ok: true, why: ''};
    return {ok: src.ok !== false, why: String(src.why || '')};
  }

  function inertButtons(buttons, on) {
    (buttons || []).forEach(function (b) {
      if (b.__title === undefined) b.__title = b.title || '';
      var dis = !model.state || !on;
      if (b.disabled !== dis) b.disabled = dis;
      var tip = on ? b.__title : STREAM_OFF_TIP;
      if (b.title !== tip) { b.title = tip; b.setAttribute('aria-label', tip); }
    });
  }

  function paintStreamPicker(picker, src, on) {
    picker.set(src);
    inertButtons(picker.buttons, on);
    var off = on ? 'false' : 'true';
    if (picker.root.getAttribute('data-off') !== off) picker.root.setAttribute('data-off', off);
    try { if (ui.chooser) paintChooser(); } catch (err) { /* the chooser never breaks the header */ }
  }

  function openChooser(anchor) {
    closeChooser();
    var host = ui.pop;
    if (!host) return;
    var back = make('div', 'pl-choose-back');
    var card = make('div', 'pl-choose');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'PineStream - which screen');
    card.appendChild(make('b', 'pl-choose-title', 'Stream which screen?'));
    card.appendChild(make('small', 'pl-choose-sub', 'Listeners see it in a corner of the stream page. Nothing streams until you pick one.'));
    var row = make('div', 'pl-choose-row');
    var buttons = {};
    STREAM_SOURCES.forEach(function (o) {
      var b = make('button', 'pl-choose-btn');
      b.type = 'button';
      b.setAttribute('data-source', o.value);
      b.appendChild(iconNode(o.icon));
      b.appendChild(make('b', '', chooserLabel(o.value)));
      var note = make('small', 'pl-choose-note', '');
      b.appendChild(note);
      b.title = 'Stream ' + streamSourceName(o.value) + ' to listeners now';
      b.setAttribute('aria-label', b.title);
      b.addEventListener('click', function (e) { e.stopPropagation(); chooseStream(o.value, b); });
      row.appendChild(b);
      buttons[o.value] = {root: b, note: note};
    });
    card.appendChild(row);
    back.appendChild(card);
    back.addEventListener('click', function (e) { if (e.target === back) { e.stopPropagation(); closeChooser(); } });
    card.addEventListener('click', function (e) { e.stopPropagation(); });
    host.appendChild(back);
    /* anchored under the switch that asked, kept inside the popup */
    try {
      var pr = host.getBoundingClientRect();
      var ar = (anchor || host).getBoundingClientRect();
      var w = card.offsetWidth || 360;
      card.style.top = Math.max(8, Math.round(ar.bottom - pr.top + 6)) + 'px';
      card.style.left = Math.max(8, Math.min(Math.round(ar.left - pr.left - 24), Math.round(pr.width - w - 8))) + 'px';
    } catch (err) { /* the stylesheet's own spot */ }
    var x = null;
    try { if (typeof root.pineCloseX === 'function') x = root.pineCloseX(card, function () { closeChooser(); }, {label: 'Cancel - PineStream stays off'}); } catch (err) { x = null; }
    if (!x) {
      x = btn('pl-choose-x', '', 'c:close--filled', 'Cancel - PineStream stays off');
      x.addEventListener('click', function (e) { e.stopPropagation(); closeChooser(); });
      card.appendChild(x);
    }
    /* Escape is this chooser's before it is the popup's: the window's
     * capture phase runs ahead of every document listener */
    var key = function (e) {
      if (e.key !== 'Escape' && e.key !== 'Esc') return;
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      closeChooser();
    };
    root.addEventListener('keydown', key, true);
    ui.chooser = {back: back, card: card, buttons: buttons, key: key, focused: false};
    paintChooser();
    paint();
  }

  function paintChooser() {
    var c = ui.chooser;
    if (!c) return;
    var last = streamSource();
    var other = last === 'pinetab' ? 'pineapp' : 'pinetab';
    var ready = {};
    STREAM_SOURCES.forEach(function (o) {
      var r = streamSourceReady(o.value);
      ready[o.value] = r;
      var b = c.buttons[o.value];
      setClass(b.root, 'unready', !r.ok);
      setText(b.note, r.ok ? (o.value === last ? 'last used' : '') : r.why + ' - you can still pick it');
    });
    /* the last-used screen, unless it cannot stream and the other can */
    var pre = (!ready[last].ok && ready[other].ok) ? other : last;
    STREAM_SOURCES.forEach(function (o) {
      var on = o.value === pre;
      setClass(c.buttons[o.value].root, 'pre', on);
      c.buttons[o.value].root.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (!c.focused) {
      c.focused = true;
      try { c.buttons[pre].root.focus({preventScroll: true}); } catch (err) { /* focus is a nicety */ }
    }
  }

  function closeChooser() {
    var c = ui.chooser;
    if (!c) return;
    ui.chooser = null;
    try { root.removeEventListener('keydown', c.key, true); } catch (err) { /* gone */ }
    if (c.back.parentNode) c.back.parentNode.removeChild(c.back);
    paint();
  }

  function chooseStream(v, node) {
    closeChooser();
    if (!model.settings) model.settings = {};
    model.settings.stream_source = v;
    model.settings.stream_on = true;
    if (model.state && model.state.stream) { model.state.stream.on = true; model.state.stream.source = v; }
    paint();
    return act('/api/pinelive/settings', {stream_source: v, stream_on: true}, node);
  }

