  /* ================================================== [pinestream] PineStream */
  /* "add a section here for enabling a pip stream of the pinetab / pineapp to
   *  be streamed to the stream page. I want users able to enable and disable
   *  it at will like the pinecam and call it pinestream."
   * The switch is settings.stream_on on the same road as PineCam to live
   * (/api/pinelive/settings, remembered by the station); the screen is
   * settings.stream_source. Off by default, and while it is off nothing is
   * captured or served anywhere (pinestream.py). One model value paints the
   * header's switch and the panel's twin; one function flips both. */
  var STREAM_SOURCES = [
    {value: 'pinetab', label: 'PineTab', icon: 'c:screen', title: 'PineStream shows the PineTab\'s screen'},
    {value: 'pineapp', label: 'Pine app', icon: 'c:laptop', title: 'PineStream shows the Pine app\'s window on the desk'}
  ];

  function streamBlock() { return (model.state && model.state.stream) || {}; }

  function streamOn() {
    var s = model.settings || {};
    return s.stream_on !== undefined ? !!s.stream_on : !!streamBlock().on;
  }

  function streamSource() {
    var s = model.settings || {};
    var v = s.stream_source || streamBlock().source || 'pinetab';
    return v === 'pineapp' ? 'pineapp' : 'pinetab';
  }

  function streamSourceName(v) { return (v || streamSource()) === 'pineapp' ? 'the Pine app' : 'the PineTab'; }

  /* immediate, like PineCam to live: both twins move now, the station stops
   * serving now, and the answer's state puts them right if it refused */
  function flipStream(next, node) {
    if (!model.settings) model.settings = {};
    model.settings.stream_on = next;
    if (model.state && model.state.stream) model.state.stream.on = next;
    paint();
    return act('/api/pinelive/settings', {stream_on: next}, node);
  }

  function pickStreamSource(v) {
    if (v !== 'pinetab' && v !== 'pineapp') return;
    saveSetting('stream_source', v);
    paint();
  }

  /* two small icon buttons under one another, the header's height */
  function streamSourcePicker(parent) {
    var box = make('div', 'pl-hsw-src');
    box.setAttribute('role', 'radiogroup');
    box.setAttribute('aria-label', 'Which screen PineStream shows');
    var buttons = STREAM_SOURCES.map(function (o) {
      var b = make('button');
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', 'false');
      b.title = o.title;
      b.setAttribute('aria-label', o.title);
      b.appendChild(iconNode(o.icon));
      b.__value = o.value;
      b.addEventListener('click', function (e) { e.stopPropagation(); pickStreamSource(o.value); });
      box.appendChild(b);
      return b;
    });
    parent.appendChild(box);
    return {root: box, buttons: buttons, set: function (v) {
      buttons.forEach(function (b) {
        var on = b.__value === v ? 'true' : 'false';
        if (b.getAttribute('aria-checked') !== on) b.setAttribute('aria-checked', on);
      });
    }};
  }

  function paintStreamSwitch(h) {
    if (!h || !h.stream) return;
    var on = streamOn();
    var src = streamSource();
    h.stream.set(on);
    var live = on ? 'true' : 'false';
    if (h.stream.root.getAttribute('data-live') !== live) h.stream.root.setAttribute('data-live', live);
    setText(h.stream.label, on ? 'PineStream · LIVE' : 'PineStream');
    h.stream.root.title = on
      ? 'PineStream is LIVE to listeners: they see ' + streamSourceName(src) + ' in a corner of the stream page. Tap to stop it at once - nothing is captured or served while it is off.'
      : 'PineStream is OFF: nothing is captured or served. Tap to show ' + streamSourceName(src) + ' to listeners as a picture-in-picture on the stream page.';
    if (h.streamSrc) {
      h.streamSrc.set(src);
      h.streamSrc.buttons.forEach(function (b) { b.disabled = !model.state; });
    }
    var p = ui.panels && ui.panels.stream;
    if (p && p.chip) {
      setText(p.chip, on ? 'LIVE to listeners' : '');
      setClass(p.chip, 'pl-chip-live', on);
      setHidden(p.chip, !on);
    }
  }

