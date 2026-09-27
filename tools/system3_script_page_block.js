  /* ------------------------------ System 3: THE MESSENGER AND THE TECHNICAL VIEW
   *
   * "The script view needs to be inherently connected to these systems and
   *  be able to be an alternative view as well ... cycle between the
   *  developing conversation view, the technical RNG generative view of the
   *  scaffolding view and back to the script view in sync." (System 3.pdf,
   *  p.5) - and, from the Script tab: "i need to be able to cycle to
   *  messenger view from the script tab to the technical view and the
   *  messenger view."
   *
   * Two buttons on the band toolbar swap THIS pane between the script and
   * System 3's own views of the round the script is on: the Rolodex (every
   * recorded roll behind every line) and the messenger (the conversation as
   * System 3 directed it). The lit button pressed again is the way back to
   * the script, which lands on the turn picked in either view. The views
   * are the station's own module, imported by absolute URL exactly as the
   * word-cause graph is (techUrl, #1386), so they reach the tablet with no
   * APK rebuild.
   *
   * IN SYNC WITH WHAT IS SPOKEN, without the faults #1288-#1298 name: the
   * line on air (or the line tapped, while its card is open) is looked up
   * in the conversation's own line map on this page's tick - no request per
   * line. A request is made only when the air reaches a line that belongs
   * to no conversation on show: one GET, then one conversation fetch, once
   * per round. The pane sits over the script in the script's own grid cell,
   * so the script underneath keeps following the air untouched. */
  var s3Mode = 'script';
  var s3View = null;
  var s3Opening = null;
  var s3Buttons = {};
  var s3Asked = '';
  var s3RetryAt = 0;
  var s3Busy = false;
  var s3Picked = '';

  function s3Request(path, options) {
    var method = String((options && options.method) || 'GET').toUpperCase();
    var fn = method === 'POST' ? 'post' : (method === 'PUT' ? 'put' : 'get');
    var bridge = api();
    if (!bridge || typeof bridge[fn] !== 'function') {
      return Promise.reject(new Error('the station bridge cannot ' + method));
    }
    return Promise.resolve(bridge[fn](path,
      options && options.body ? JSON.parse(options.body) : undefined));
  }

  function s3Reset() {
    if (s3View) { try { s3View.dispose(); } catch (e) { /* already gone */ } }
    s3View = null;
    s3Opening = null;
    s3Mode = 'script';
    s3Buttons = {};
    s3Asked = '';
    s3Busy = false;
    s3Picked = '';
  }

  function s3Mount() {
    if (s3View) return Promise.resolve(s3View);
    if (s3Opening) return s3Opening;
    var pane = el('spS3');
    if (!pane) return Promise.resolve(null);
    s3Opening = (async function () {
      try {
        if (!document.getElementById('spS3Style')) {
          var style = document.createElement('link');
          style.id = 'spS3Style';
          style.rel = 'stylesheet';
          style.href = techUrl('/system3/system3.css?v=3');
          document.head.appendChild(style);
        }
        var mod = await import(techUrl('/system3/system3.js?v=3'));
        pane.textContent = '';
        var box = make('div', 'sp-s3-host');
        pane.appendChild(box);
        s3View = await mod.mountEmbedded(box, {
          request: s3Request,
          view: s3Mode === 'technical' ? 'rolodex' : 'conversation',
          onSelect: function (pick) {
            s3Picked = (pick && pick.lines && pick.lines[0]) || '';
          },
          onOpenFull: function () {
            try {
              if (typeof root.system3Open === 'function') { root.system3Open(); return; }
            } catch (e) { /* not the panel's document */ }
            try { root.open(techUrl('/system3'), '_blank'); } catch (e) { /* no opener */ }
          }
        });
        return s3View;
      } catch (err) {
        pane.textContent = '';
        pane.appendChild(make('div', 'sp-techbad',
          'System 3 could not open here: ' + String((err && err.message) || err)));
        return null;
      } finally { s3Opening = null; }
    })();
    return s3Opening;
  }

  /* The line System 3's views follow: the one tapped while its card is
     open, else the one on air, else (only when asked) the last one. */
  function s3FocusLine(onAir, fallback) {
    var detail = el('spDetail');
    if (detail && !detail.hidden) {
      var picked = document.querySelector('#spScript .sp-el.picked[data-line]');
      if (picked) return String(picked.dataset.line || '');
    }
    if (onAir) return onAir;
    if (!fallback) return '';
    var all = document.querySelectorAll('#spScript .sp-el[data-line]');
    return all.length ? String(all[all.length - 1].dataset.line || '') : '';
  }

  /* A sting or an interjection between two turns belongs to no turn: the
     spoken lines just above it are asked about next. */
  function s3Around(id) {
    var out = id ? [id] : [];
    var node = id ? lineNode(id) : null;
    while (node && out.length < 3) {
      node = node.previousElementSibling;
      if (node && node.dataset && node.dataset.line
          && out.indexOf(String(node.dataset.line)) < 0) {
        out.push(String(node.dataset.line));
      }
    }
    return out;
  }

  async function s3Resolve(line) {
    s3Busy = true;
    s3Asked = line;
    s3RetryAt = Date.now() + 20000;
    try {
      var tries = s3Around(line);
      var got = null;
      for (var i = 0; i < tries.length && !got; i += 1) {
        var r = null;
        try {
          r = await s3Request('/api/system3/line?line_id=' + encodeURIComponent(tries[i]));
        } catch (e) { r = null; }
        if (r && r.line && r.conversation) got = r;
      }
      if (!s3View) return;
      if (got) {
        var cid = got.conversation.conversation_id;
        await s3View.show({
          conversationId: cid,
          turnId: (got.turn && got.turn.turn_id) || '',
          refresh: s3View.conversationId === cid,
          note: tries[0] !== got.line.line_id
            ? 'The line in focus is a sting or an interjection; this is the turn it follows.' : ''});
        s3View.live(got.line.line_id);
        return;
      }
      if (s3View.conversationId) return;          /* keep what is on show */
      var list = null;
      try { list = await s3Request('/api/system3/conversations?limit=1'); } catch (e) { list = null; }
      var last = list && list.conversations && list.conversations[0];
      if (last) {
        await s3View.show({conversationId: last.conversation_id,
          note: 'The line in focus was not directed by System 3 (a record link, an advert, an ID, '
            + 'or a round written before it was switched on). This is its latest conversation.'});
      } else {
        s3View.message('System 3 has not directed a conversation yet: it plans every banter '
          + 'and call round the station writes.');
      }
    } catch (err) {
      /* the script carries on underneath */
    } finally { s3Busy = false; }
  }

  /* Once per tick, only while a System 3 view is up. Cheap when the air has
     not moved: one Array.find over the round's own lines. */
  function s3Tick(onAir, force) {
    if (s3Mode === 'script' || !s3View) return;
    var line = s3FocusLine(onAir, !!force);
    if (!line) return;
    if (s3View.live(line) === 'here') { s3Asked = line; return; }
    if (!force && line === s3Asked && Date.now() < s3RetryAt) return;
    if (s3Busy) return;
    s3Resolve(line);
  }

  function s3SetMode(mode) {
    if (mode === s3Mode || (mode !== 'technical' && mode !== 'messenger')) mode = 'script';
    s3Mode = mode;
    var pane = el('spS3');
    Object.keys(s3Buttons).forEach(function (k) {
      s3Buttons[k].setAttribute('aria-pressed', String(k === mode));
    });
    if (host) host.classList.toggle('sp-s3-on', mode !== 'script');
    if (mode === 'script') {
      if (pane) pane.hidden = true;
      var back = s3Picked;
      s3Picked = '';
      if (back) jumpToLine(back);
      return;
    }
    if (pane) pane.hidden = false;
    s3Mount().then(function (view) {
      if (!view || s3Mode === 'script') return;
      view.setView(s3Mode === 'technical' ? 'rolodex' : 'conversation');
      var row = null;
      try { row = activeRow(); } catch (e) { row = null; }
      s3Tick(row ? String(row.id || '') : '', true);
    });
  }

