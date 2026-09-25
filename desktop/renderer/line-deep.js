/* WHY THIS LINE WAS SAID, AND WHY IT KEEPS COMING BACK.
 *
 * "By examining it, I want to see a 3JS flow chart taking me through the
 * path of how it came to be through everything as far as the structures of
 * sending it through the recording room, the writing room, and got it
 * scheduled to be put on the broadcast. I also want to see information on
 * how many times it played, how often it's played, when the last time it
 * played was, and why it keeps coming up so often."
 *
 * FIVE STATIONS ARE ASKED, and each answers a different half of that:
 *
 *   /api/dj/provenance/{id}   the writing room - the brief, the prompt as
 *                             sent, the script that came back, the crystal
 *                             shards, the vector searches and the source
 *                             documents. This is "what chunk caused it".
 *                             It 404s past the booth's 240-row ring, which
 *                             is said plainly rather than shown as a gap.
 *   /api/pipeline/detail      the recording room and the road out - the
 *                             engine, the milliseconds, the shelf row, the
 *                             schedule entry, and which step the work is
 *                             standing on.
 *   /api/cupboard/worn        the repetition. Its rows carry `aired` and
 *                             its phrases carry `said_in_lines`, which
 *                             together are the honest answer to "why does
 *                             this keep coming up": not a guess, a count.
 *   /api/airlog               every time this line actually went out, so
 *                             "how often" and "when last" are read off the
 *                             air log rather than inferred.
 *   /api/dj/scenario          the scene (#1113). "Offer a dropdown that
 *                             shows what the scenario was that is being
 *                             used for setting the scenario. Also next to
 *                             it put a drop down arrow that I can hit and
 *                             it basically opens a box showing all the
 *                             scenarios that are currently being used to
 *                             basically create this scene. So if there's a
 *                             topic, if there's a guest star, if there's
 *                             any of these options inside the pine box
 *                             agent that's affecting this scenario to make
 *                             it happen, I want access to them so I can
 *                             see how the scenario came to be." The
 *                             station answers with the scenario in force
 *                             for the line and EVERY input the agent has -
 *                             topic, plotline, guest, theme, crystals,
 *                             tint, prompt, persona, mood, running order -
 *                             each marked on or off. The off ones are
 *                             drawn dimmed rather than left out, so the
 *                             operator sees the option exists and is not
 *                             shaping this scene. With no line id it is
 *                             still asked, and answers with the scene in
 *                             force now.
 *
 * EVERY ROAD ON THE STRIP OPENS (#1149). "I want to tap on these and be
 * able to expand each of them to see additional details about what these
 * roads entail and what contributed to each of them." The chain of dots is
 * eight roads, and each is now a button sitting under its own dot: it says
 * what that road IS, in two plain sentences, and then what it actually put
 * into THIS line - read off the same answers gather() already holds. A road
 * the record cannot speak for says so plainly ("the tint left no mark on
 * this line"), because a panel that invents a contribution is worse than one
 * that admits a gap. The dots were already drawn filled or empty; filled now
 * means exactly "this panel has something to show", so the glance and the
 * panel cannot disagree. The numbered stepper below opens on the same rule -
 * one at a time, tap it again to shut it - and shows everything the record
 * holds for that step and nothing it does not.
 *
 * THE 3D IS THE SHAPE, THE TEXT IS THE RECORD. The flow is drawn because a
 * path with branches is worth seeing as space; every number under it is
 * text, because a bar chart made of cubes is harder to read than a bar
 * chart. The diagram is the glance and the list below is the authority.
 */
(function (root) {
  'use strict';

  /* Resolved, not assumed: a leading slash is the station on the tablet and
   * the root of the DISK under file://. See pineThreeUrl in renderer.js. */
  function threeUrl() {
    if (window.pineThreeUrl) return window.pineThreeUrl();
    if (/^https?:$/.test(location.protocol)) return '/vendor/three.min.js';
    return 'http://127.0.0.1:8096/vendor/three.min.js';
  }
  var threeLoad = null;

  var box = null;
  var scene = null;
  var openFor = null;
  var styleUrl = typeof document !== 'undefined' && document.currentScript
    && document.currentScript.src
    ? new URL('line-deep.css', document.currentScript.src).href : '';

  function ensureStyles() {
    if (!styleUrl || document.querySelector('link[data-pine-line-deep]')) return;
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = styleUrl;
    link.setAttribute('data-pine-line-deep', '');
    document.head.appendChild(link);
  }
  /* #1149: which road on the strip is open. One at a time - "tapping the
   * open stage again closes it; tapping another switches". Cleared with the
   * window, because it names a road on a line that is no longer on screen. */
  var openStage = null;

  /* ======================================== #1231: TAP A BOX AND TYPE IN IT
   *
   * "in Any text field, allow me to tap on it and type inside of it and
   *  begin making edits there."
   *
   * EVERY BOX HERE IS A READING OF SOMETHING. Some of those things are
   * stores the station can be told to change - the topics in the bank, the
   * director's weather, the station disposition, a seat's character, a
   * road's system prompt, the caller theme, the seated guest, a speakbox
   * passage, a crystal shard, and the round's own turns. The rest are
   * records of what already happened, and a record cannot be rewritten
   * after the fact. A box of the second kind still answers the tap, with
   * the reason on a strip under it: a control that does nothing at all is
   * worse than one that refuses out loud.
   *
   * ONE DOOR. PUT /api/paperwork/field {scope, key, value, was, line_id,
   * apply} - the station decides which store a scope names, keeps the
   * (used) flags and the ids of a reworded topic, sends a round's turn
   * through the writers room (a kept round is COPIED and only the changed
   * line re-records), and answers with the sentence that goes on the
   * strip. The client never guesses which box is writable: every scene
   * card carries an `edit` note from scene_inputs() naming the scope,
   * which of the card's two boxes is the store, and why when it is
   * neither.
   *
   * NOTHING REPAINTS UNDER AN OPEN EDITOR. While a field is dirty or holds
   * the caret, paint() returns, open() will not rebuild the sheet, and a
   * tap outside will not dismiss it - the whole point of typing into a box
   * is that the box is still there when you look up. Esc cancels. BLUR DOES
   * NOT: on a tablet the soft keyboard steals focus constantly, and a blur
   * that threw the words away would make this unusable.
   *
   * THE SOFT KEYBOARD. Android shrinks the VISUAL viewport and leaves the
   * layout viewport alone, so a fixed, centred window stays centred on a
   * viewport that is no longer on the glass - the modal simply slides off
   * the screen the moment you tap into it. While an editor is open the box
   * is re-centred on window.visualViewport at every resize and scroll, and
   * the caret is put back in view.
   */
  var edits = [];                /* [#1231] every editor open on this sheet */
  var vvWatch = null;
  var closeAsk = 0;

  var READING_ONLY =
    'this box is the record of what happened, not a store the station can be '
    + 'told to change. The boxes that can be typed in are the ones with a '
    + 'dotted underline.';

  function editsDirty() {                                      // [#1231]
    for (var i = 0; i < edits.length; i += 1) {
      if (edits[i].dirty) return true;
    }
    return false;
  }

  function editsBusy() {                                       // [#1231]
    for (var i = 0; i < edits.length; i += 1) {
      if (edits[i].dirty) return true;
      if (edits[i].area && edits[i].area === document.activeElement) return true;
    }
    return false;
  }

  /* The flag and the shout. Local to this modal, as asked - but other
   * surfaces poll the same page, so the state is also readable
   * (body[data-pine-editing]) and announced once per change. */
  function markBusy() {                                        // [#1231]
    var on = editsBusy();
    try {
      if (on) document.body.setAttribute('data-pine-editing', 'line-deep');
      else if (document.body.getAttribute('data-pine-editing') === 'line-deep') {
        document.body.removeAttribute('data-pine-editing');
      }
      root.dispatchEvent(new CustomEvent('pine-edit-busy',
        {detail: {busy: on, where: 'line-deep'}}));
    } catch (e) { /* an old view: the flag is a courtesy, the guard is above */ }
    return on;
  }

  function fitViewport() {                                     // [#1231]
    var vv = root.visualViewport;
    if (!box || !vv) return;
    box.style.maxHeight = Math.max(200, Math.round(vv.height) - 16) + 'px';
    box.style.top = Math.round(vv.offsetTop + vv.height / 2) + 'px';
  }

  function keyboardWatch(on) {                                 // [#1231]
    var vv = root.visualViewport;
    if (!vv) return;
    if (on && !vvWatch) {
      vvWatch = function () { fitViewport(); };
      vv.addEventListener('resize', vvWatch);
      vv.addEventListener('scroll', vvWatch);
      fitViewport();
    } else if (!on && vvWatch) {
      vv.removeEventListener('resize', vvWatch);
      vv.removeEventListener('scroll', vvWatch);
      vvWatch = null;
      if (box) { box.style.maxHeight = ''; box.style.top = ''; }
    }
  }

  /* A strip under a box: why it cannot be typed in, or what the station
   * said when it was. It replaces its own previous strip rather than
   * stacking, so tapping a refusing box twice does not build a wall. */
  function note(node, words, bad) {                            // [#1231]
    var host = node && node.parentNode;
    if (!host) return;
    var after = node.nextSibling;
    if (after && after.classList
        && after.classList.contains('ld-edit-strip')) after.remove();
    var strip = make('div', 'ld-edit-strip' + (bad ? ' bad' : ''));
    strip.appendChild(make('span', 'ld-edit-say', String(words || READING_ONLY)));
    var ok = make('button', 'ld-edit-btn', 'got it');
    ok.type = 'button';
    ok.addEventListener('click', function (e) {
      e.stopPropagation();
      strip.remove();
    });
    strip.appendChild(ok);
    host.insertBefore(strip, node.nextSibling);
  }

  function grow(area) {                                        // [#1231]
    try {
      area.style.height = 'auto';
      area.style.height = Math.max(64, Math.min(320, area.scrollHeight + 4)) + 'px';
    } catch (e) { /* no layout yet */ }
  }

  /* Mark a box as a field. `spec` with a scope opens an editor; `spec`
   * without one answers the tap with spec.why. */
  function editable(node, spec) {                              // [#1231]
    if (!node || node.getAttribute('data-ld-edit') === '1') return node;
    node.setAttribute('data-ld-edit', '1');
    if (spec && spec.scope) {
      node.classList.add('ld-tap');
      node.title = 'tap to type in it';
    }
    node.addEventListener('click', function (e) {
      var sel = root.getSelection ? root.getSelection() : null;
      if (sel && String(sel).length > 1) return;   /* selecting, not tapping */
      e.stopPropagation();
      openEditor(node, spec);
    });
    return node;
  }

  function openEditor(node, spec) {                            // [#1231]
    spec = spec || {};
    if (!spec.scope) { note(node, spec.why); return; }
    var host = node.parentNode;
    if (!host) return;
    var after = node.nextSibling;
    if (after && after.classList
        && after.classList.contains('ld-edit-strip')) after.remove();

    var was = node.textContent;
    var wrap = make('div', 'ld-edit');
    var area = document.createElement('textarea');
    area.className = 'ld-edit-area';
    area.value = was;
    area.spellcheck = false;
    area.setAttribute('aria-label', String(spec.label || 'this box'));
    wrap.appendChild(area);

    var strip = make('div', 'ld-edit-strip');
    var say = make('span', 'ld-edit-say', String(spec.how || spec.label || ''));
    strip.appendChild(say);

    /* "applies to: future rounds / this round too" only where BOTH are
     * meaningful. Where only one is, it is stated rather than offered as a
     * choice that is not one. */
    var applies = (spec.applies && spec.applies.length) ? spec.applies : ['future'];
    var pick = null;
    if (applies.length > 1) {
      pick = make('select', 'ld-edit-applies');
      pick.setAttribute('aria-label', 'what this edit applies to');
      var optF = make('option', '', 'applies to: future rounds');
      optF.value = 'future';
      pick.appendChild(optF);
      var optR = make('option', '', 'applies to: this round too');
      optR.value = 'round';
      pick.appendChild(optR);
      strip.appendChild(pick);
    } else {
      strip.appendChild(make('i', 'ld-edit-only', applies[0] === 'round'
        ? 'applies to: this round' : 'applies to: future rounds'));
    }

    var save = make('button', 'ld-edit-btn save', 'Save');
    save.type = 'button';
    var cancel = make('button', 'ld-edit-btn', 'Cancel');
    cancel.type = 'button';
    strip.appendChild(save);
    strip.appendChild(cancel);
    wrap.appendChild(strip);

    var rec = {area: area, wrap: wrap, node: node, dirty: false};
    edits.push(rec);
    host.replaceChild(wrap, node);
    grow(area);
    keyboardWatch(true);

    function shut(text) {
      var at = edits.indexOf(rec);
      if (at >= 0) edits.splice(at, 1);
      rec.dirty = false;
      if (text !== undefined && text !== null) node.textContent = text;
      if (wrap.parentNode) wrap.parentNode.replaceChild(node, wrap);
      if (!edits.length) keyboardWatch(false);
      markBusy();
    }

    function fail(words) {
      save.disabled = false;
      cancel.disabled = false;
      strip.classList.add('bad');
      say.textContent = String(words || 'the station refused it');
      try { area.focus(); } catch (e) { /* gone */ }
    }

    function send() {
      var body = {scope: String(spec.scope), key: String(spec.key || ''),
        value: area.value, was: was, line_id: String(spec.lineId || ''),
        apply: pick ? pick.value : applies[0]};
      save.disabled = true;
      cancel.disabled = true;
      strip.classList.remove('bad');
      say.textContent = 'saving...';
      var door = api();
      var call = (typeof door.put === 'function')
        ? door.put('/api/paperwork/field', body)
        : door.post('/api/paperwork/field', body);
      call.then(function (got) {
        got = got || {};
        if (got.ok === false) {
          fail(got.detail || got.say || 'the station refused it');
          return;
        }
        shut(got.changed === false ? was : area.value);
        note(node, String(got.say || 'saved'), false);
      }, function (err) {
        fail((err && err.message) || String(err));
      });
    }

    area.addEventListener('input', function () {
      rec.dirty = area.value !== was;
      grow(area);
      markBusy();
    });
    area.addEventListener('focus', function () {
      markBusy();
      setTimeout(function () {
        try { area.scrollIntoView({block: 'center'}); }
        catch (e) { area.scrollIntoView(); }
        fitViewport();
      }, 220);
    });
    /* Blur keeps the words. See the header: the tablet takes focus away
     * every time the keyboard opens or closes. */
    area.addEventListener('blur', function () { markBusy(); });
    area.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' || e.keyCode === 27) {
        e.preventDefault();
        e.stopPropagation();
        shut();
      } else if ((e.ctrlKey || e.metaKey)
                 && (e.key === 'Enter' || e.keyCode === 13)) {
        e.preventDefault();
        send();
      }
    });
    cancel.addEventListener('click', function (e) { e.stopPropagation(); shut(); });
    save.addEventListener('click', function (e) { e.stopPropagation(); send(); });
    wrap.addEventListener('click', function (e) { e.stopPropagation(); });
    try { area.focus(); } catch (e) { /* gone */ }
    markBusy();
  }

  /* The window. A DIRTY editor is not thrown away by a stray tap outside
   * or by the close button: the strip says what to do instead, and a
   * second press within four seconds discards it on purpose. */
  function closeAsked() {                                      // [#1231]
    if (!editsDirty()) { close(); return; }
    var now = Date.now();
    if (now - closeAsk < 4000) { close(); return; }
    closeAsk = now;
    var open_ = null;
    for (var i = 0; i < edits.length; i += 1) {
      if (edits[i].dirty) { open_ = edits[i]; break; }
    }
    if (!open_) { close(); return; }
    var strip = open_.wrap && open_.wrap.querySelector('.ld-edit-strip');
    if (strip) {
      strip.classList.add('bad');
      var words = strip.querySelector('.ld-edit-say');
      if (words) {
        words.textContent = 'there is an edit open here - Save it or Cancel '
          + 'it. Close again to throw it away.';
      }
    }
    try {
      open_.wrap.scrollIntoView({block: 'center'});
      open_.area.focus();
    } catch (e) { /* gone */ }
  }

  /* The scene card's own note, read into a spec for one of its two boxes.
   * `which` is 'value' (the head line) or 'detail' ("the whole of it"). */
  function cardSpec(i, which) {                                // [#1231]
    var meta = (i && i.edit) || {};
    var boxes = meta.boxes || [];
    if (meta.scope && boxes.indexOf(which) >= 0) {
      return {scope: String(meta.scope), key: String(meta.key || ''),
        label: String(meta.label || i.label || ''),
        how: String(meta.how || ''),
        applies: meta.applies || ['future'],
        lineId: openFor ? String(openFor.id || '') : ''};
    }
    if (meta.scope) {
      return {scope: '', why: 'the head line is the station summary of this '
        + 'box, not the box - open "the whole of it" below and type in there.'};
    }
    return {scope: '', why: String(meta.why || READING_ONLY)};
  }


  /* What a hand-over state means, in the operator's words rather than the
   * row's. Read by the "handed over" step and by the on-air road. */
  var ROADS = {
    stream: 'the stream', box: 'the box', both: 'both outputs',
    published: 'the page, awaiting playback', page: 'the page',
    airing: 'on the air now', prepared: 'written, never heard',
    held: 'held back', analysis: 'analysis only - never for the air',
    failed: 'the audio failed', withdrawn: 'refused at hand-over'
  };

  function api() {
    return root.pineDesktop || {
      get: function () { return Promise.reject(new Error('no bridge')); },
      post: function () { return Promise.reject(new Error('no bridge')); }
    };
  }

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = threeUrl();
      tag.onload = function () { resolve(root.THREE); };
      tag.onerror = function () { threeLoad = null; reject(new Error('no three.js')); };
      document.head.appendChild(tag);
    });
    return threeLoad;
  }

  function ago(seconds) {
    var s = Number(seconds);
    if (!isFinite(s) || s < 0) return '';
    if (s < 90) return Math.round(s) + 's ago';
    if (s < 5400) return Math.round(s / 60) + 'm ago';
    if (s < 172800) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + ' days ago';
  }

  function boiled(v) {
    return String(v || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ')
      .replace(/[ ]+/g, ' ').trim();
  }

  /* MILLISECONDS, BOTH WAYS. The station's own numbers are milliseconds and
   * the operator reads seconds; neither is dropped. */
  function millis(n) {
    var v = Number(n);
    if (!isFinite(v) || v <= 0) return '';
    if (v < 1000) return Math.round(v) + ' ms';
    return (v / 1000).toFixed(1) + ' s  \u00b7  ' + Math.round(v) + ' ms';
  }

  /* A TIME, WHICHEVER SHAPE IT ARRIVED IN. /api/said/why's `flow` rows carry
   * `at` already struck as a clock ("01:18:04"); the steps built here carry
   * an epoch. Number('01:18:04') is NaN, which is why the station's own
   * times were landing blank in the stepper's right-hand column. */
  function stamp(at) {
    if (at === null || at === undefined || at === '') return '';
    if (typeof at === 'string' && /^\d{1,2}:\d{2}(:\d{2})?$/.test(at)) return at;
    return clock(at);
  }

  /* THE CHAT ROW, FROM WHICHEVER DOOR THE LINE CAME IN. hot-corners.js hands
   * the whole row on `line.row` - delivery_id, page_delivery, withdrawn_why,
   * the render/written trace - while line-actions.js builds its line from a
   * DOM node and has none of that. The provenance answer carries its own
   * copy of the row, which has the clip cut and the air time but never the
   * delivery ids. Both are read, the live row wins where they overlap, and
   * nothing absent from both is guessed at. */
  function rowOf(line, all) {
    var out = {};
    var mine = (line && line.row) || {};
    var theirs = ((all && all.prov) || {}).line || {};
    var k;
    for (k in theirs) {
      if (Object.prototype.hasOwnProperty.call(theirs, k)) out[k] = theirs[k];
    }
    for (k in mine) {
      if (Object.prototype.hasOwnProperty.call(mine, k)) out[k] = mine[k];
    }
    return out;
  }

  /* /api/said/why answers with two lists keyed by `name`: `systems` (on/off
   * with a note) and `properties` (a value and the desk it is set on). Both
   * are looked up by name, so a name the station stops sending goes quiet
   * rather than throwing. */
  function byName(rows) {
    var map = {};
    (rows || []).forEach(function (r) {
      if (r && r.name) map[String(r.name).toLowerCase()] = r;
    });
    return map;
  }

  /* One row of the station's own flow, by its `step` key: called, written,
   * rendered, handed, heard, ledger. Absent for a line the station has no
   * flow for, and absent per-step - a board clip has no `written`. */
  function flowAt(why, step) {
    var found = null;
    ((why && why.flow) || []).forEach(function (f) {
      if (!found && f && String(f.step || '') === step) found = f;
    });
    return found;
  }

  /* A fact, or nothing at all. An empty value is DROPPED rather than shown
   * as a blank row: "never invent a contribution" cuts both ways, and a
   * named row with nothing beside it reads as a fact that failed. */
  function put(list, name, value) {
    if (value === null || value === undefined) return list;
    var s = String(value).trim();
    if (!s || s === '\u00b7') return list;
    list.push({name: name, value: s});
    return list;
  }

  function putFold(list, name, text) {
    var s = (text === null || text === undefined) ? '' : String(text);
    if (!s.trim()) return list;
    list.push({name: name, text: s});
    return list;
  }

  function putCrystal(list, name, value, record, kind) {
    list.push({name: name, value: String(value || 'detail retained'),
      detail: {record: record, kind: kind}});
  }

  function crystalEvidence(record, kind) {
    var wrap = make('div', 'ld-crystal-evidence');
    record = record && typeof record === 'object' ? record : {};
    var grade = String(record.passage_grade || '');
    var gradeWords = {
      measured: 'Measured: exact swath retained from the writing prompt.',
      written: 'Written: closest historical passage; exact prompt swath was not retained.',
      current: 'Current: document opening as it stands now; this is not the historical prompt.',
      absent: 'Absent: the passage was not retained.'
    };
    if (kind === 'document' || grade) {
      wrap.appendChild(make('p', 'ld-passage-grade', gradeWords[grade]
        || 'Passage grade not retained; exact historical match is unknown.'));
    }
    if (record.passage_how) {
      wrap.appendChild(make('p', 'ld-passage-how', String(record.passage_how)));
    }
    var rest = {};
    Object.keys(record).forEach(function (key) {
      if (key !== 'text' && (key !== 'snippet' || !!record.text)
          && key !== 'passage_grade'
          && key !== 'passage_how') rest[key] = record[key];
    });
    if (Object.keys(rest).length) {
      wrap.appendChild(make('pre', 'ld-pre ld-crystal-meta', JSON.stringify(rest, null, 2)));
    }
    if (kind === 'system') {
      if (!Object.keys(rest).some(function (key) { return String(rest[key] || '').trim(); })) {
        wrap.appendChild(make('p', 'ld-passage-missing',
          'No further system detail was retained for this line.'));
      }
      return wrap;
    }
    var passage = grade === 'absent' ? ''
      : String(record.text || (kind === 'document' ? record.snippet || '' : ''));
    if (!passage.trim()) {
      wrap.appendChild(make('p', 'ld-passage-missing', kind === 'vector'
        ? 'Passage not retained for this search.'
        : 'Passage not retained for this source.'));
      return wrap;
    }
    if (!grade && kind === 'document' && !record.text) {
      wrap.appendChild(make('p', 'ld-passage-how',
        'Legacy excerpt; whether these exact words reached the writer is unknown.'));
    }
    wrap.appendChild(editable(make('pre', 'ld-pre', passage), record.file
      ? {scope: 'passage', key: String(record.file), applies: ['future'],
         label: 'a source passage',
         how: 'Save asks the station to update matching words in '
           + String(record.file) + ' for future rounds.'}
      : {scope: '', why: 'The record names no source file for this passage.'}));
    return wrap;
  }

  /* The two shapes a fact can take, rendered: a name/value row on the
   * sheet's own list, or - for a prompt, a script, a brief - a fold over the
   * whole of it verbatim, which is the file's existing idiom. */
  function factsInto(node, facts) {
    var list = null;
    facts.forEach(function (f) {
      if (f.detail) {
        var detail = make('details', 'ld-fold ld-crystal-fold');
        var summary = make('summary', '');
        summary.appendChild(make('b', '', f.name));
        summary.appendChild(make('span', '', f.value || 'detail retained'));
        detail.appendChild(summary);
        detail.appendChild(crystalEvidence(f.detail.record, f.detail.kind));
        node.appendChild(detail);
        list = null;
        return;
      }
      if (f.text) {
        var d = make('details', 'ld-fold');
        d.appendChild(make('summary', '', f.name));
        d.appendChild(make('pre', 'ld-pre', f.text));
        node.appendChild(d);
        list = null;
        return;
      }
      if (!list) { list = make('ul', 'ld-facts'); node.appendChild(list); }
      list.appendChild(fact(f.name, f.value));
    });
  }

  /* Every airing of THIS line inside the air log's 48-hour window. Shared by
   * the "how often" sheet and by the on-air road's panel, so the two can
   * never quote different counts off the same log. */
  function airHits(line, all) {
    var rows = (((all || {}).air || {}).rows || ((all || {}).air || {}).entries || [])
      .filter(function (r) { return r && (r.text || r.id); });
    var mine = boiled(line && line.said);
    var hits = rows.filter(function (r) {
      if (r.id && line && String(r.id) === line.id) return true;
      var t = boiled(r.text);
      return t && mine && (t === mine || (mine.length > 30 && t.indexOf(mine.slice(0, 30)) >= 0));
    });
    var whens = hits.map(function (r) { return Number(r.at || r.ts || 0); })
      .filter(Boolean).sort(function (a, b) { return b - a; });
    return {read: rows.length, hits: hits, whens: whens};
  }

  /* ------------------------------------------------------------ the shell */

  function close() {
    edits.length = 0;            // [#1231] the window is going; so are its fields
    keyboardWatch(false);        // [#1231] before the box leaves the document
    markBusy();                  // [#1231]
    if (scene && scene.stop) { try { scene.stop(); } catch (e) { /* gone */ } }
    scene = null;
    openFor = null;
    openStage = null;
    if (box) { box.remove(); box = null; }
  }

  function open(line) {
    /* [#1231] A second swipe of the corner, or another tap on the feed,
     * must not throw away words that are half typed. */
    if (editsDirty()) { closeAsked(); return; }
    close();
    ensureStyles();
    openFor = line;
    box = make('div', 'ld-box');
    box.innerHTML =
      '<div class="ld-head">'
      + '<b>How this line came to be</b>'
      + '<div class="ld-head-actions">'
      + '<button class="ld-forget" type="button" aria-label="Forget this line" title="Forget this line"></button>'
      + '<button class="ld-close" type="button" aria-label="close" title="close">×</button>'
      + '</div></div>'
      + '<div class="ld-forget-feedback" role="status" aria-live="polite" hidden></div>'
      /* #1113 the scene row. Until the station answers, the select says
       * so; sceneRow() replaces the whole row once gather() is back. */
      + '<div class="ld-scene"><div class="ld-scene-bar">'
      + '<select class="ld-scene-pick" disabled aria-label="the scenario">'
      + '<option>reading the scene…</option></select>'
      + '</div></div>'
      + '<p class="ld-said"></p>'
      + '<div class="ld-flow"><canvas class="ld-canvas"></canvas>'
      + '<div class="ld-flowwhy"></div></div>'
      + '<div class="ld-body"></div>';
    document.body.appendChild(box);
    var opened = box;
    var forget = box.querySelector('.ld-forget');
    var canForget = !!String(line.id || '').trim() && !!String(line.said || '').trim();
    forget.disabled = !canForget;
    if (!canForget) forget.title = 'A line ID and spoken text are needed to forget it';
    if (typeof root.pineIcon === 'function') {
      forget.innerHTML = root.pineIcon('c:trash-can', 'Forget this line');
    } else {
      forget.setAttribute('data-pine-icon', 'c:trash-can');
      if (typeof root.pineIconUpgrade === 'function') root.pineIconUpgrade(forget);
    }
    forget.addEventListener('click', function (e) {
      e.stopPropagation();
      if (!forget.disabled) askForget(opened, line);
    });
    if (root.PineDuck) root.PineDuck.hold('line-deep', root.PineDuck.REPORT, box);   /* 2026-09-14: a diagnostic ducks the broadcast */
    /* [#1231] The WHOLE line, not 300 characters of it: this box is now
     * an editor, and an editor showing a truncation would save one. The
     * stylesheet caps its height instead. */
    box.querySelector('.ld-said').textContent = String(line.said || '').slice(0, 4000);
    box.querySelector('.ld-close').addEventListener('click', function (e) {
      e.stopPropagation();
      closeAsked();              // [#1231] a dirty field is asked about first
    });
    if (root.PineDismiss) root.PineDismiss.watch(box, closeAsked, []);   // [#1231]
    /* [#1231] Any box nobody wired still answers the tap, with the reason.
     * Delegated, so a panel drawn later by a road or a step is covered too. */
    box.addEventListener('click', function (e) {
      var hit = e.target && e.target.closest
        ? e.target.closest('.ld-pre, .ld-scene-value') : null;
      if (!hit || hit.getAttribute('data-ld-edit') === '1') return;
      var sel = root.getSelection ? root.getSelection() : null;
      if (sel && String(sel).length > 1) return;
      note(hit, READING_ONLY);
    });

    var body = box.querySelector('.ld-body');
    body.appendChild(make('p', 'ld-wait', 'asking the station…'));
    gather(line).then(function (all) {
      if (box !== opened) return;
      paint(line, all);
    }, function (err) {
      if (box !== opened) return;
      sceneRow(line, null);
      body.replaceChildren();
      body.appendChild(make('p', 'ld-wait',
        'the station could not say: ' + ((err && err.message) || err)));
    });
  }

  function forgetFeedback(opened, words, bad) {
    if (box !== opened) return;
    var feedback = opened.querySelector('.ld-forget-feedback');
    feedback.hidden = false;
    feedback.classList.toggle('bad', !!bad);
    feedback.textContent = words;
  }

  function askForget(opened, line) {
    if (box !== opened || opened.querySelector('.ld-forget-confirm')) return;
    if (editsBusy()) {
      forgetFeedback(opened, 'Save or cancel the open edit before forgetting this line.', true);
      return;
    }
    var ask = make('div', 'ld-forget-confirm');
    ask.appendChild(make('span', '', 'Forget this line? This cannot be undone.'));
    var yes = make('button', 'ld-forget-yes', 'Forget line');
    yes.type = 'button';
    var no = make('button', 'ld-forget-no', 'Keep line');
    no.type = 'button';
    ask.appendChild(yes);
    ask.appendChild(no);
    opened.querySelector('.ld-head').insertAdjacentElement('afterend', ask);
    no.addEventListener('click', function (e) {
      e.stopPropagation();
      ask.remove();
    });
    yes.addEventListener('click', function (e) {
      e.stopPropagation();
      yes.disabled = true;
      no.disabled = true;
      forgetFeedback(opened, 'Forgetting this line...', false);
      Promise.resolve().then(function () {
        return api().post('/api/said/forget', {
          line_id: String(line.id), text: String(line.said)
        });
      }).then(function (got) {
        if (!got || got.ok !== true) {
          throw new Error((got && (got.detail || got.say || got.error))
            || 'The station did not confirm deletion.');
        }
        ask.remove();
        forgetFeedback(opened, String(got.say || 'Line forgotten.')
          + ' Refreshing...', false);
        setTimeout(function () {
          if (box === opened) close();
          if (root.location && typeof root.location.reload === 'function') {
            root.location.reload();
          }
        }, 1200);
      }).catch(function (err) {
        yes.disabled = false;
        no.disabled = false;
        forgetFeedback(opened, 'Could not forget this line: '
          + ((err && err.message) || String(err)), true);
      });
    });
  }

  /* Five asks, in parallel, each allowed to fail on its own. A missing
   * provenance must not cost the repetition count, and a scene the station
   * cannot read (#1113) must not cost the sheet. The scene is asked even
   * when the line has no id: `line=` empty is the station's cue to answer
   * with the scene in force now. encodeURIComponent(undefined) would send
   * the word "undefined", which is why the id is defaulted first. */
  function gather(line) {
    var soft = function (p) {
      return p.then(function (v) { return v; }, function () { return null; });
    };
    return Promise.all([
      soft(api().get('/api/dj/provenance/' + encodeURIComponent(line.id))),
      soft(api().get('/api/pipeline/detail?kind=voice')),
      soft(api().get('/api/cupboard/worn?most=60')),
      soft(api().get('/api/airlog?limit=400')),
      soft(api().get('/api/dj/scenario?line=' + encodeURIComponent(line.id || ''))),
      /* 2026-09-14, the hot corners: what SET the line (#1117) - round,
       * voice, engine, model, aired state, the systems that were on - is
       * the sixth ask, for the stepper at the top of the body. It 404s
       * for a line in neither the booth nor the air log, and that is
       * allowed to fail like the others. */
      soft(api().get('/api/said/why/' + encodeURIComponent(line.id || '')))
    ]).then(function (got) {
      return {prov: got[0], road: got[1], worn: got[2], air: got[3], scene: got[4],
        why: got[5]};
    });
  }

  /* ------------------------------------------------------------- painting */

  function section(into, title, node) {
    if (!node) return;
    var wrap = make('div', 'ld-sec');
    wrap.appendChild(make('h4', '', title));
    wrap.appendChild(node);
    into.appendChild(wrap);
  }

  function paint(line, all) {
    /* [#1231] replaceChildren() below would take the box the operator is
     * typing into out of the document with their words still in it. */
    if (editsBusy()) return;
    var body = box.querySelector('.ld-body');
    body.replaceChildren();

    /* #1149: the panel a tapped road opens is the FIRST thing in the
     * scrolling body, so it hangs directly off the strip above it and still
     * cannot push the window past the tablet's 1154x690 glass. Empty until a
     * road is tapped, and emptied again with every repaint. */
    openStage = null;
    body.appendChild(make('div', 'ld-stage-host'));

    var stages = stageFacts(line, all);
    drawFlow(box.querySelector('.ld-canvas'), stages).then(function (made) {
      scene = made;
      if (!made) box.querySelector('.ld-flow').classList.add('flat');
    }, function () { scene = null; });
    stageBar(line, all, stages);
    canvasTaps(line, all, stages);

    sceneRow(line, all.scene);

    /* 2026-09-14, the hot corners: "a flow by flow flow chart explaining
     * everything that's happened as far as how this piece of line came to
     * be broadcasted and all the parameters pertaining to it." At the TOP,
     * before the admin options, because it is the answer to the question
     * the corner swipe asked. */
    /* [#1231] The line itself is a box too, and the most useful one: tap
     * it and you are editing that turn of the round it belongs to. The
     * station said whether there IS one - /api/said/why answers `edit`
     * with the shelf id and which turn this line is - so a line made live,
     * or one whose round has been retired, says so rather than failing at
     * the Save. */
    var saidBox = box.querySelector('.ld-said');
    var rnd = (all.why && all.why.ok && all.why.edit) || null;
    if (saidBox) {
      if (rnd && rnd.banked && Number(rnd.index) >= 0) {
        editable(saidBox, {scope: 'turn', key: '',
          label: 'this line, in the round it belongs to',
          how: 'turn ' + (Number(rnd.index) + 1) + ' of ' + rnd.turns
            + ' in the banked ' + (rnd.kind || 'round') + ' ' + rnd.sid
            + (rnd.kept
              ? ' - it has already aired, so the round is COPIED and only '
                + 'this line re-records'
              : ' - only this line re-records'),
          applies: ['round'], lineId: String(line.id || '')});
      } else {
        editable(saidBox, {scope: '', why: (rnd && rnd.why)
          || 'the station holds no banked round behind this line, so there '
             + 'are no written words to rewrite'});
      }
    }

    section(body, 'how this line came to be broadcast, step by step', flowNode(line, all));
    section(body, 'admin options - what reached this line', adminNode(all));   /* 2026-09-14 */
    section(body, 'how often it has gone out', timesNode(line, all));
    section(body, 'why it keeps coming up', whyNode(line, all));
    section(body, 'the room that wrote it', wroteNode(all));
    section(body, 'what it was shown', shownNode(all));
    section(body, 'the road, step by step', roadNode(all));
    section(body, 'if you never want to hear it again', retireNode(line, all));
  }

  /* ---------------------------------------------------------- the stepper */

  /* 2026-09-14, THE HOT CORNERS' INSPECTOR. "If I swipe from the left
   * corner up to the center, I want to basically bring up a dialogue
   * window of what just happened. So basically it's an inspector window
   * that shows the last line of dialogue or the active playing dialogue,
   * and it gives me a flow by flow flow chart explaining everything that's
   * happened as far as how this piece of line came to be broadcasted and
   * all the parameters pertaining to it."
   *
   * A vertical stepper - numbered nodes joined by a line - built from what
   * gather() already fetches: /api/said/why (round, voice, engine, model,
   * aired, the systems that were on), the provenance (written.model and
   * .at, render.engine/.voice/.ms, schedule.kind/.prompt, how/prepared),
   * and the ledger's place, which reaches the page only as data-block /
   * data-ord on a script row (script-page.js #1330) or as block/ord on
   * the line object itself. In this order when known:
   *
   *   the round was called  ->  the line was written  ->  rendered  ->
   *   handed over  ->  heard at  ->  the ledger's place
   *
   * A step the station could not say is drawn dimmed, with the reason as
   * its detail - never invented. If the station's answer carries
   * `why.flow` ([{step, label, detail, at}]) that is rendered instead,
   * verbatim: the server may start writing the flow itself.
   */
  function clock(at) {
    var t = Number(at);
    if (!isFinite(t) || t <= 0) return '';
    if (t > 1e12) t = t / 1000;                      /* milliseconds */
    if (t < 1e9) return '';                          /* not an epoch */
    var d = new Date(t * 1000);
    var two = function (n) { return (n < 10 ? '0' : '') + n; };
    return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
  }

  function ledgerPlace(line, all) {
    var node = line && line.node;
    var why = (all && all.why) || {};
    var row = ((all && all.prov) || {}).line || (line && line.row) || {};
    var b = null, o = null;
    var cands = [
      [line && line.block, line && line.ord],
      [why.block, why.ord],
      [row.block, row.ord],
      [node && node.dataset ? node.dataset.block : null,
        node && node.dataset ? node.dataset.ord : null]
    ];
    for (var i = 0; i < cands.length; i += 1) {
      var cb = cands[i][0], co = cands[i][1];
      if (cb === undefined || cb === null || cb === '' || co === undefined || co === null || co === '') continue;
      b = String(cb); o = String(co);
      break;
    }
    return b === null ? null : {block: b, ord: o};
  }

  function flowSteps(line, all) {
    var why = (all.why && all.why.ok) ? all.why : null;
    var prov = all.prov || {};
    var row = prov.line || (line && line.row) || {};
    var written = prov.written || {};
    var render = prov.render || {};
    var sched = prov.schedule || {};
    var now = Date.now() / 1000;

    if (why && why.flow && why.flow.length) {
      /* The station's own flow, verbatim - and its `step` key carried
       * through, because #1149 opens each of these and the key is what says
       * which half of the record to open it with. */
      return why.flow.map(function (f) {
        f = f || {};
        return {key: String(f.step || ''), label: String(f.label || f.step || ''),
          detail: String(f.detail || ''), at: f.at, known: true};
      });
    }

    var steps = [];
    var join = function (bits) {
      return bits.filter(function (b) { return !!b; }).join('  ·  ');
    };

    /* 1. the round was called */
    var kind = String(sched.kind || row.kind || (why && why.kind) || '');
    var round = String(row.round || (why && why.round) || '');
    steps.push({
      key: 'called',
      label: 'the round was called',
      detail: join([
        kind ? 'the ' + kind + ' road' : '',
        round ? 'round ' + round : '',
        sched.prompt ? 'brief: ' + String(sched.prompt).slice(0, 160) : '',
        prov.how === 'shelf' ? 'served off the shelf' : (prov.how ? String(prov.how) : ''),
        prov.prepared ? String(prov.prepared) : ''
      ]) || 'the station did not say why this round was called',
      at: written.at || row.ts,
      known: !!(kind || round)
    });

    /* 2. the line was written */
    var model = String(written.model || (why && why.model) || '');
    var on = [];
    if (why && why.systems) {
      why.systems.forEach(function (s) { if (s && s.on) on.push(String(s.name)); });
    }
    var place = ledgerPlace(line, all);
    steps.push({
      key: 'written',
      label: 'the line was written',
      detail: join([
        model ? 'by ' + model : '',
        written.ms ? Number(written.ms) + ' ms' : '',
        round ? 'round ' + round : '',
        place ? 'block ' + place.block + '.' + place.ord : '',
        on.length ? 'with ' + on.join(', ') : '',
        written.at ? 'committed ' + clock(written.at) : ''
      ]) || (all.prov === null
        ? 'past the booth’s 240-row ring: the writing room can no longer be asked'
        : 'no paperwork is held for the writing of this line'),
      at: written.at || row.ts,
      known: !!(model || written.prompt)
    });

    /* 3. rendered */
    var engine = String(render.engine || row.engine || (why && why.engine) || '');
    var voice = String(render.voice || row.voice || (why && why.voice) || '');
    var seconds = Number(row.seconds || (line && line.row && line.row.seconds) || 0);
    steps.push({
      key: 'rendered',
      label: 'rendered',
      detail: join([
        engine ? 'on ' + engine : '',
        voice ? 'voice ' + voice : '',
        seconds ? seconds.toFixed(1) + ' s' : '',
        render.ms ? Number(render.ms) + ' ms to render' : '',
        render.fallback ? 'fell back from ' + String(render.fallback) : ''
      ]) || 'no render is recorded for this line',
      at: null,
      known: !!(engine || voice || seconds)
    });

    /* 4. handed over */
    var aired = String((why && why.aired) || row.aired || (line && line.row && line.row.aired) || '');
    steps.push({
      key: 'handed',
      label: 'handed over',
      detail: aired ? 'state ' + aired + ' - ' + (ROADS[aired] || 'an output the page does not name')
        : 'no hand-over is recorded',
      at: null,
      known: !!aired
    });

    /* 5. heard at */
    var airAt = Number(row.air_at || (line && line.row && line.row.air_at) || 0);
    steps.push({
      key: 'heard',
      label: 'heard at',
      detail: airAt ? clock(airAt) + (now > airAt ? '  (' + ago(now - airAt) + ')' : '  (yet to come)')
        : 'no air time is recorded',
      at: airAt || null,
      known: !!airAt
    });

    /* 6. the ledger's place */
    steps.push({
      key: 'ledger',
      label: 'the ledger’s place',
      detail: place ? 'block ' + place.block + ', line ' + place.ord + ' of the script ledger'
        : 'not on the script ledger as far as this page can see - minted outside a round, or opened from a row that carries no place',
      at: null,
      known: !!place
    });
    return steps;
  }

  /* EVERYTHING THE RECORD HOLDS FOR ONE NUMBERED STEP (#1149). "I want to
   * tap on these and be able to expand each of them to see additional
   * details about what these roads entail and what contributed to each of
   * them" - the stepper opens on the same rule as the strip above it.
   *
   * Keyed on the station's own step names, so a flow the server writes and a
   * flow built here open the same drawer. Only fields that are really there
   * are shown: put() drops an empty value rather than printing a blank row,
   * and a step with nothing under it says so instead of inventing.
   *
   * WHAT IS NOT HERE, and why. /api/said/why answers with no delivery_id, no
   * page_delivery and no withdrawn_why - the hand-over drawer reads those
   * off the chat row, which hot-corners.js hands over whole and
   * line-actions.js (which builds its line from a DOM node) cannot. Opened
   * from a held line, the hand-over step says the page was not handed the
   * reason rather than pretending there was none. */
  /* [#1195] Which alternative of the segment prompt book governed the
     call that wrote this line, and what every command in it became -
     one line, so the card can say "written with the hard sell, and the
     speaker box handed it fmn1.md" without a fold. */
  function altSay(alt) {
    if (!alt || typeof alt !== 'object') return '';
    var out = alt.name ? ('\u201c' + String(alt.name) + '\u201d')
      : (alt.source === 'shelf' ? 'the shelf text, as it stands' : '');
    if (alt.mode) out += ' (' + String(alt.mode) + (alt.of ? ' of ' + alt.of : '') + ')';
    var ex = alt.expanded || [];
    var bits = [];
    for (var i = 0; i < ex.length; i += 1) {
      var e = ex[i] || {};
      bits.push(String(e.cmd || '') + (e.doc ? ' \u2192 ' + e.doc
        : (e.miss ? ' \u2192 ' + e.miss : '')));
    }
    if (bits.length) out += (out ? '  \u00b7  ' : '') + bits.join(', ');
    return out;
  }

  function moreFor(key, line, all) {
    var d = record(line, all);
    var f = [];
    var now = Date.now() / 1000;

    if (key === 'called') {
      put(f, 'the road', propOf(d, 'the road') || d.sched.kind || d.row.kind);
      put(f, 'the round', d.row.round || (d.why && d.why.round));
      put(f, 'the brief', d.sched.prompt);
      put(f, 'how it was made', d.prov.prepared
        || (d.prov.how === 'live' ? 'made live, while you were listening' : d.prov.how));
      put(f, 'written in the same pass', Number(d.prov.burst) > 0
        ? Number(d.prov.burst) + ' lines' : '');
      put(f, 'the scene it was called into', d.scene
        ? String(d.scene.label || '') + (d.scene.road ? '  ·  ' + d.scene.road + ' road' : '')
        : '');
      return f;
    }
    if (key === 'written') {
      put(f, 'the model', d.written.model || (d.why && d.why.model) || propOf(d, 'the model'));
      put(f, 'time to write', millis(d.written.ms));
      put(f, 'what it returned', Number(d.written.chars) > 0
        ? Number(d.written.chars) + ' characters' : '');
      put(f, 'temperature', d.written.temp);
      put(f, 'the room it had', [
        Number(d.written.budget) > 0 ? Number(d.written.budget) + ' tokens of budget' : '',
        Number(d.written.num_ctx) > 0 ? Number(d.written.num_ctx) + ' of context' : ''
      ].filter(function (b) { return !!b; }).join('  ·  '));
      put(f, 'committed', clock(d.written.at));
      put(f, 'the brief it answered', d.sched.prompt);
      put(f, 'the kind of round', d.written.kind);
      put(f, 'the instruction dialled', altSay(d.sched.alternative));   /* [#1195] */
      putFold(f, 'the prompt as sent', d.written.prompt);
      putFold(f, 'what came back', d.written.script);
      return f;
    }
    if (key === 'rendered') {
      put(f, 'the engine', d.render.engine || d.row.engine || (d.why && d.why.engine));
      put(f, 'the voice', d.render.voice || d.row.voice || (d.why && d.why.voice)
        || propOf(d, 'the voice'));
      put(f, 'the service', d.render.service);
      put(f, 'time to render', millis(d.render.ms));
      put(f, 'the audio measured', Number(d.render.seconds) > 0
        ? Number(d.render.seconds).toFixed(2) + ' s' : (Number(d.row.seconds) > 0
          ? Number(d.row.seconds).toFixed(2) + ' s (off the row, not the engine)' : ''));
      put(f, 'how big', Number(d.render.kb) > 0 ? Number(d.render.kb) + ' KB' : '');
      put(f, 'it fell back', d.render.fallback ? 'from ' + String(d.render.fallback) : '');
      put(f, 'engines tried first', (d.render.tried || []).join(', '));
      return f;
    }
    if (key === 'handed') {
      var aired = String((d.why && d.why.aired) || d.row.aired || '');
      put(f, 'the road', propOf(d, 'the road') || d.row.kind);
      put(f, 'the row’s state', aired
        ? aired + ' - ' + (ROADS[aired] || 'an output the page does not name') : '');
      put(f, 'the page delivery', d.row.page_delivery);
      put(f, 'the delivery id', d.row.delivery_id);
      put(f, 'the clip it was cut from', d.row.clip_media
        ? String(d.row.clip_media) + (Number(d.row.clip_from) >= 0
          ? ' at ' + Number(d.row.clip_from).toFixed(2) + 's' : '') : '');
      if (d.row.withdrawn_why) {
        put(f, 'why it was refused', d.row.withdrawn_why);
      } else if (aired === 'withdrawn') {
        put(f, 'why it was refused',
          'the row was withdrawn but the page was not handed the reason');
      }
      return f;
    }
    if (key === 'heard') {
      var airAt = Number(d.row.air_at || 0);
      put(f, ['withdrawn', 'held', 'failed', 'prepared', 'analysis']
        .indexOf(String((d.why && d.why.aired) || d.row.aired || '')) >= 0
        ? 'the slot it would have taken' : 'the air time', airAt
        ? clock(airAt) + (now > airAt ? '  (' + ago(now - airAt) + ')' : '  (yet to come)') : '');
      put(f, 'how long it ran', Number(d.row.seconds) > 0
        ? Number(d.row.seconds).toFixed(1) + ' s' : '');
      var hits = airHits(line, all);
      if (hits.read) {
        put(f, 'times in the 48-hour air log', String(hits.hits.length));
        if (hits.whens.length) put(f, 'last heard', ago(now - hits.whens[0]));
      }
      return f;
    }
    if (key === 'ledger') {
      if (d.place) {
        put(f, 'the block', d.place.block);
        put(f, 'the line in that block', d.place.ord);
      }
      var led = flowAt(d.why, 'ledger');
      if (led) {
        put(f, 'the ledger says', led.label);
        put(f, 'how it got there', String(led.detail || '') === 'scripted'
          ? 'scripted - the running order authored it before the round went out'
          : led.detail);
      }
      if (!d.place && !led) {
        put(f, 'not on the ledger',
          'this page can see no block and line for it - minted outside a round, '
          + 'or opened from a row that carries no place');
      }
      return f;
    }
    return f;
  }

  function flowNode(line, all) {
    var steps = flowSteps(line, all);
    if (!steps.length) return null;
    var wrap = make('div', '');
    var list = make('ol', 'ld-stepper');

    /* One drawer open at a time, the same rule as the strip: tap the open
     * step to shut it, tap another and it takes over. */
    var shutAll = function () {
      Array.prototype.forEach.call(list.querySelectorAll('.ld-step'), function (row) {
        var pane = row.querySelector('.ld-step-more');
        if (pane) pane.hidden = true;
        row.classList.remove('open');
        row.setAttribute('aria-expanded', 'false');
      });
    };

    steps.forEach(function (s, i) {
      var li = make('li', 'ld-step tap' + (s.known ? '' : ' unknown'));
      li.appendChild(make('i', 'ld-step-n', String(i + 1)));
      var body = make('div', 'ld-step-body');
      body.appendChild(make('b', '', s.label));
      if (s.detail) body.appendChild(make('p', '', s.detail));
      li.appendChild(body);
      li.appendChild(make('span', 'ld-step-at', stamp(s.at)));
      /* Carbon, from the station's own sprite - the caret says the row opens
       * without spending a word on saying it. */
      var caret = make('span', 'ld-step-caret');
      if (typeof root.pineIcon === 'function') {
        caret.innerHTML = root.pineIcon('c:caret--right');
      }
      li.appendChild(caret);

      var pane = make('div', 'ld-step-more');
      pane.hidden = true;
      li.appendChild(pane);
      li.setAttribute('role', 'button');
      li.setAttribute('tabindex', '0');
      li.setAttribute('aria-expanded', 'false');

      var toggle = function (e) {
        if (e) e.stopPropagation();
        var want = pane.hidden;
        shutAll();
        if (!want) return;
        if (!pane.firstChild) {
          var more = moreFor(s.key, line, all);
          if (more.length) factsInto(pane, more);
          else pane.appendChild(make('p', 'ld-dim',
            'the record holds nothing further for this step'));
        }
        pane.hidden = false;
        li.classList.add('open');
        li.setAttribute('aria-expanded', 'true');
      };
      li.addEventListener('click', toggle);
      li.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.keyCode === 13 || e.keyCode === 32) {
          e.preventDefault();
          toggle(e);
        }
      });
      list.appendChild(li);
    });
    wrap.appendChild(list);
    var why = all.why;
    if (why && why.say) wrap.appendChild(make('p', 'ld-dim ld-step-say', String(why.say)));
    else if (why === null || (why && why.ok === false)) {
      wrap.appendChild(make('p', 'ld-dim ld-step-say',
        'the station could not say what set this line (/api/said/why answered nothing)'));
    }
    return wrap;
  }

  /* ------------------------------------------------------------ the scene */

  /* #1113 THE SCENE ROW, directly under the head. Two controls:
   *
   *   the select   its first, selected option is the scenario in force for
   *                this line ("call with banter · caller road"); the rest
   *                are the inputs that are ON, one per line ("Topic: ...").
   *                Choosing one is a jump, not a setting: it opens the box,
   *                lights and unfolds that input's card, then the select
   *                goes straight back to the scenario option, so it always
   *                reads as "what scene is this" at a glance.
   *   the caret    opens the box that lists EVERY input as a card, on and
   *                off alike. Off cards are dimmed, not dropped: "if there's
   *                any of these options inside the pine box agent that's
   *                affecting this scenario ... I want access to them" - and
   *                the option he does not see is the one he cannot reach
   *                for. The box is shut by default; the head row is the
   *                glance and the box is the record.
   *
   * Called with null when the station could not say, in which case the row
   * says so in one line and nothing else on the sheet is touched. */
  function sceneRow(line, got) {
    var row = box && box.querySelector('.ld-scene');
    if (!row) return;
    row.replaceChildren();
    /* Clicks in a select or the box must not read as a tap outside. */
    row.addEventListener('click', function (e) { e.stopPropagation(); });

    if (!got || !got.ok || !got.scenario) {
      row.classList.add('unread');
      row.appendChild(make('span', 'ld-scene-none', 'the scene could not be read'));
      return;
    }
    var sc = got.scenario || {};
    var inputs = (got.inputs || []).filter(function (i) { return i && i.key; });
    var on = inputs.filter(function (i) { return !!i.on; });

    var pick = make('select', 'ld-scene-pick');
    pick.setAttribute('aria-label', 'the scenario this line was written to');
    var first = make('option', '', String(sc.label || 'the scene')
      + (sc.road ? ' · ' + String(sc.road) + ' road' : ''));
    first.value = '';
    pick.appendChild(first);
    on.forEach(function (i) {
      var opt = make('option', '', String(i.label || i.key) + ': '
        + String(i.value || '').slice(0, 80));
      opt.value = String(i.key);
      pick.appendChild(opt);
    });
    pick.selectedIndex = 0;

    var caret = make('button', 'ld-scene-caret');
    caret.type = 'button';
    caret.setAttribute('aria-expanded', 'false');
    caret.setAttribute('aria-label', 'everything shaping this scene');
    caret.title = 'everything shaping this scene';
    if (typeof root.pineIcon === 'function') {
      caret.innerHTML = root.pineIcon('c:caret--right');
    } else {
      caret.textContent = '>';
    }

    var sheet = make('div', 'ld-scene-box');
    sheet.hidden = true;
    var top = make('div', 'ld-scene-top');
    top.appendChild(make('b', '', String(sc.label || 'the scene')));
    var bits = [];
    if (sc.kind) bits.push(String(sc.kind));
    if (sc.road) bits.push(String(sc.road) + ' road');
    if (sc.where) bits.push('set on ' + String(sc.where));
    if (Number(sc.since) > 0) {
      bits.push('in force since ' + ago(Date.now() / 1000 - Number(sc.since)));
    }
    if (bits.length) top.appendChild(make('i', '', bits.join('  ·  ')));
    if (sc.brief) top.appendChild(make('p', 'ld-dim', String(sc.brief).slice(0, 600)));
    sheet.appendChild(top);
    if (!inputs.length) {
      sheet.appendChild(make('p', 'ld-dim',
        'the station listed nothing that is shaping this scene'));
    }
    inputs.forEach(function (i) { sheet.appendChild(sceneCard(i)); });
    if (got.say) sheet.appendChild(make('p', 'ld-dim ld-scene-say', String(got.say)));

    function show(want) {
      sheet.hidden = !want;
      caret.setAttribute('aria-expanded', want ? 'true' : 'false');
      caret.classList.toggle('open', !!want);
    }
    caret.addEventListener('click', function (e) {
      e.stopPropagation();
      show(sheet.hidden);
    });
    pick.addEventListener('change', function () {
      var key = pick.value;
      pick.selectedIndex = 0;
      if (!key) return;
      show(true);
      var card = null;
      Array.prototype.some.call(sheet.querySelectorAll('.ld-scene-card'), function (c) {
        if (c.getAttribute('data-key') === key) { card = c; return true; }
        return false;
      });
      if (!card) return;
      var fold = card.querySelector('details');
      if (fold) fold.open = true;
      card.classList.add('lit');
      setTimeout(function () { card.classList.remove('lit'); }, 1600);
      try { card.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
      catch (e) { card.scrollIntoView(); }
    });

    var bar = make('div', 'ld-scene-bar');
    bar.appendChild(pick);
    bar.appendChild(caret);
    row.appendChild(bar);
    row.appendChild(sheet);
  }

  /* One input, as a card: what it is, whether it is on, its value, the
   * whole of it behind a fold, why it shapes the scene, and which desk
   * it is managed on. */
  function sceneCard(i) {
    var card = make('div', 'ld-scene-card' + (i.on ? '' : ' off'));
    card.setAttribute('data-key', String(i.key));
    var head = make('div', 'ld-scene-cardhead');
    head.appendChild(make('b', '', String(i.label || i.key)));
    head.appendChild(make('i', 'ld-scene-state',
      i.on ? 'shaping this scene' : 'off'));
    card.appendChild(head);
    /* [#1232] the weather card says whether its numbers were rolled
     * for this round or are the fixed reading. */
    if (i.key === 'mood' && i.roll && typeof i.roll === 'object') {
      var rolled = i.roll.mode === 'random';
      var badge = make('i', 'ld-scene-roll' + (rolled ? ' rolled' : ''));
      if (rolled && typeof root.pineIcon === 'function') {
        badge.innerHTML = root.pineIcon('c:shuffle');
      }
      badge.appendChild(document.createTextNode(rolled
        ? ('rolled for this round'
           + (i.roll.seed != null ? ' \u00b7 seed ' + String(i.roll.seed) : '')
           + (i.roll.why ? ' \u00b7 ' + String(i.roll.why) : ''))
        : ('fixed' + (i.roll.macro ? ' \u00b7 macro ' + String(i.roll.macro) : ''))));
      card.appendChild(badge);
    }
    if (i.value) {
      card.appendChild(editable(make('p', 'ld-scene-value', String(i.value)),
        cardSpec(i, 'value')));                       // [#1231]
    } else if (!i.on) {
      card.appendChild(make('p', 'ld-scene-value ld-dim', 'nothing set'));
    }
    if (i.detail) {
      var d = make('details', 'ld-fold');
      d.appendChild(make('summary', '', 'the whole of it'));
      d.appendChild(editable(make('pre', 'ld-pre', String(i.detail)),
        cardSpec(i, 'detail')));                      // [#1231]
      card.appendChild(d);
    }
    if (i.why) card.appendChild(make('p', 'ld-scene-why', String(i.why)));
    if (i.desk) {
      card.appendChild(make('span', 'ld-scene-desk',
        'manage on the ' + String(i.desk) + ' desk'));
    }
    return card;
  }

  /* ------------------------------------------------- the roads on the strip */

  /* ONE READING OF THE RECORD, HANDED TO EVERYTHING. stageFacts() and the
   * stepper's moreFor() both answer "what does the station hold about this
   * line", and if they read it from different places they will eventually
   * disagree in front of the operator. They read it from here.
   *
   * Two rows are worth naming. `written` and `render` come from the
   * provenance when the booth still holds the line (its last 240), and from
   * the chat row's own `trace` when it does not - hot-corners.js hands that
   * row over, and it carries the same engine/voice/ms/service the booth
   * would have said. `stages` is the station's CURRENT pipeline, not this
   * line's: /api/pipeline/detail?kind=voice answers about the last pass
   * through each room, whoever's line that was, and anything quoted from it
   * is labelled as the station's rather than this line's. */
  function record(line, all) {
    var prov = all.prov || {};
    var why = (all.why && all.why.ok) ? all.why : null;
    var r = rowOf(line, all);
    var trace = r.trace || {};
    return {
      prov: prov,
      why: why,
      row: r,
      trace: trace,
      written: prov.written || trace.written || {},
      render: prov.render || trace.render || {},
      sched: prov.schedule || {},
      sys: byName(why && why.systems),
      props: byName(why && why.properties),
      scene: (all.scene || {}).scenario || null,
      place: ledgerPlace(line, all),
      stages: (all.road || {}).stages || []
    };
  }

  function propOf(d, name) {
    var p = d.props[name];
    return p ? String(p.value || '') : '';
  }

  /* A room of the station's own pipeline, by a word in its label. Only ever
   * quoted with "the station, not this line" beside it. */
  function roomText(stages, word) {
    var got = '';
    (stages || []).forEach(function (s) {
      if (got || !s || !s.seen) return;
      if (String(s.label || '').toLowerCase().indexOf(word) >= 0) got = String(s.text || '');
    });
    return got;
  }

  /* THE EIGHT ROADS, EACH WITH WHAT IT IS AND WHAT IT PUT INTO THIS LINE.
   *
   * #1149: "I want to tap on these and be able to expand each of them to see
   * additional details about what these roads entail and what contributed to
   * each of them."
   *
   *   `what`  what the road IS, written for the operator, not for me. Two
   *           sentences at most, and true of the road on every line.
   *   `facts` what it put into THIS line, every one of them read off an
   *           answer the window already holds. Nothing here is computed from
   *           a guess: a value the station did not send is dropped by put().
   *   `got`   whether the road left a mark. The dot on the strip is drawn
   *           from this same flag, and the panel below it cannot contradict
   *           it, because a road with `got` and nothing to show is demoted
   *           to unmarked at the bottom of this function.
   *   `none`  what to say when it did not - "the tint left no mark on this
   *           line" - which is the operator's own phrasing for the answer a
   *           record cannot give. */
  function stageFacts(line, all) {
    var d = record(line, all);
    var now = Date.now() / 1000;
    var out = [];
    var stage = function (key, label, got, what, facts, none) {
      out.push({key: key, label: label, what: what, facts: facts,
        none: none, got: !!got && facts.length > 0});
    };

    /* 1. THE BRIEF - the schedule desk's standing instruction. */
    var f = [];
    var road = propOf(d, 'the road') || d.sched.kind || d.row.kind
      || (d.why && d.why.kind) || '';
    put(f, 'the road', road);
    put(f, 'the round', d.row.round || (d.why && d.why.round));
    put(f, 'what the desk asked for', d.sched.prompt);
    put(f, 'how it was made', d.prov.prepared
      || (d.prov.how === 'live' ? 'made live, while you were listening' : d.prov.how));
    put(f, 'written in the same pass', Number(d.prov.burst) > 0
      ? Number(d.prov.burst) + ' lines' : '');
    var called = flowAt(d.why, 'called');
    if (called) {
      put(f, 'the desk called it', String(called.label || '')
        + (stamp(called.at) ? '  \u00b7  ' + stamp(called.at) : ''));
    }
    /* The desk has moved on since; that later brief is shown because the
     * operator asked what the road entails, but it is labelled as a later
     * round so it is never read as this line's own instruction. */
    if (d.sched.prompt_now && d.sched.kind_now) {
      putFold(f, 'what the desk is asking for now (the ' + d.sched.kind_now
        + ' round, not this one)', d.sched.prompt_now);
    }
    stage('brief', 'the brief', !!road,
      'The brief is the standing instruction the schedule desk hands the '
      + 'booth before a word is written: which road this round is on, and '
      + 'what the round is for. Everything downstream is an answer to it.',
      f,
      'the schedule desk left no instruction on this line\u2019s record');

    /* 2. THE WRITING ROOM - the model that turned the brief into words. */
    f = [];
    put(f, 'the model', d.written.model || (d.why && d.why.model)
      || propOf(d, 'the model'));
    put(f, 'time to write', millis(d.written.ms));
    put(f, 'what it returned', Number(d.written.chars) > 0
      ? Number(d.written.chars) + ' characters' : '');
    put(f, 'temperature', d.written.temp);
    put(f, 'the room it had', [
      Number(d.written.budget) > 0 ? Number(d.written.budget) + ' tokens of budget' : '',
      Number(d.written.num_ctx) > 0 ? Number(d.written.num_ctx) + ' of context' : ''
    ].filter(function (b) { return !!b; }).join('  \u00b7  '));
    put(f, 'committed', clock(d.written.at));
    if (d.prov.system && d.prov.system.name) {
      put(f, 'the armed disposition', String(d.prov.system.name)
        + (d.prov.system.followed ? ' - followed on this line'
          : ' - armed, but not followed on this line')
        + (d.prov.system.text ? ': ' + String(d.prov.system.text) : ''));
    }
    if (d.sys['the writing room'] && !d.written.model) {
      put(f, 'the station says', d.sys['the writing room'].note);
    }
    putFold(f, 'the prompt as sent', d.written.prompt);
    putFold(f, 'what came back', d.written.script);
    stage('writing', 'the writing room', !!(d.written.model || d.written.prompt),
      'The writing room is the model that turns the brief into words. It '
      + 'runs once for the whole round, and the booth keeps its paperwork - '
      + 'prompt, answer, model, milliseconds - for its last 240 lines.',
      f,
      all.prov === null
        ? 'past the booth\u2019s 240-row ring: the writing room can no longer be '
          + 'asked about this line'
        : 'no writing-room paperwork is held for this line - nothing here was '
          + 'written by the model');

    /* 3. THE CRYSTAL - the passages and searches put in front of the writer. */
    f = [];
    var shards = d.prov.crystal || d.prov.shards || [];
    var docs = d.prov.documents || d.prov.sources || [];
    var vecs = d.prov.vectors || d.prov.searches || [];
    if (shards.length) {
      put(f, 'shards staged', shards.length + ' passage'
        + (shards.length === 1 ? '' : 's') + ' put in front of the writer');
    }
    shards.forEach(function (s) {
      putCrystal(f, String(s.crystal || s.name || s.file || 'a passage'),
        String(s.file || '') + (s.in_prompt ? ' - in the prompt' : ' - staged, not used'),
        s, 'shard');
    });
    docs.forEach(function (doc) {
      putCrystal(f, String(doc.file || doc.title || 'a document'),
        String(doc.how || '') + (doc.quoted ? ' - quoted' : ' - read, not quoted'),
        doc, 'document');
    });
    vecs.forEach(function (v) {
      putCrystal(f, 'it searched for', '\u201c' + String(v.query || v.q || '').slice(0, 90)
        + '\u201d in ' + String(v.file || '')
        + (Number(v.score) ? ' at ' + Number(v.score).toFixed(3) : ''),
        v, 'vector');
    });
    put(f, 'the crystal desk is set to', propOf(d, 'crystals'));
    if (d.sys['the crystal']) putCrystal(f, 'the station says',
      d.sys['the crystal'].note, d.sys['the crystal'], 'system');
    if (d.sys['the vector index']) putCrystal(f, 'the vector index',
      d.sys['the vector index'].note, d.sys['the vector index'], 'system');
    if (d.sys['the speakbox']) putCrystal(f, 'the speakbox',
      d.sys['the speakbox'].note, d.sys['the speakbox'], 'system');
    stage('crystal', 'the crystal', !!(shards.length || docs.length || vecs.length),
      'The crystal is the station\u2019s shelf of source passages. A shard '
      + 'staged into the prompt is a passage the writer was made to look at; '
      + 'the vector index is how it went looking for one.',
      f,
      'no shard, document or search is recorded against this line - the '
      + 'crystal left no mark on it');

    /* 4. THE TINT - the rewrite pass that puts the register on. */
    f = [];
    var tintP = d.props['the tint'];
    var tintS = d.sys['the tint'];
    var tinted = (d.trace.written && d.trace.written.tinted) || d.written.tinted || '';
    var tintRound = /tint/.test(String(d.written.kind || d.sched.kind || ''));
    put(f, 'the tint in force', tintP ? tintP.value : '');
    if (tintS && String(tintS.note || '') !== String(tintP ? tintP.value : '')) {
      put(f, tintS.on ? 'it reached this line' : 'it did not reach this line', tintS.note);
    } else if (tintS) {
      put(f, tintS.on ? 'it reached this line' : 'it did not reach this line',
        tintS.on ? 'yes - the setting above is the one it ran with' : 'no');
    }
    put(f, 'what it re-wrote', tinted);
    put(f, 'the road itself', tintRound
      ? 'a tint round - the tint IS the road this line came down' : '');
    stage('tint', 'the tint', !!((tintS && tintS.on) || tinted || tintRound),
      'The tint is the pass that puts the station\u2019s register on a line '
      + 'after the writing room has answered: the rhyme, the grading, and the '
      + 'hold on anything it cannot prove.',
      f,
      'the tint left no mark on this line');

    /* 5. THE RECORDING ROOM - the engine that made the audio. */
    f = [];
    var engine = d.render.engine || d.row.engine || (d.why && d.why.engine) || '';
    var voice = d.render.voice || d.row.voice || (d.why && d.why.voice)
      || propOf(d, 'the voice') || '';
    put(f, 'the engine', engine);
    put(f, 'the voice', voice);
    put(f, 'the seat', propOf(d, 'the seat') || d.row.name);
    put(f, 'the service', d.render.service);
    put(f, 'time to render', millis(d.render.ms));
    put(f, 'what came out', [
      Number(d.render.kb) > 0 ? Number(d.render.kb) + ' KB' : '',
      Number(d.render.seconds) > 0 ? Number(d.render.seconds).toFixed(2) + ' s of audio' : ''
    ].filter(function (b) { return !!b; }).join('  \u00b7  '));
    put(f, 'it fell back', d.render.fallback ? 'from ' + String(d.render.fallback) : '');
    put(f, 'engines tried first', (d.render.tried || []).join(', '));
    var rendered = flowAt(d.why, 'rendered');
    if (rendered) {
      put(f, 'the station says', String(rendered.label || '')
        + (rendered.detail ? ' - ' + String(rendered.detail) : ''));
    }
    put(f, 'the room\u2019s last pass (the station, not this line)',
      roomText(d.stages, 'engine') || roomText(d.stages, 'rendered'));
    stage('recording', 'the recording room', !!(engine || voice),
      'The recording room is the voice engine. It takes the finished words '
      + 'and renders the audio the station actually plays, on whichever '
      + 'service the seat\u2019s voice is cloned on.',
      f,
      'no render is recorded for this line - nothing here was voiced');

    /* 6. THE SHELF - where a rendered round waits its turn, if it waits. */
    f = [];
    var shelf = d.sys['the shelf'];
    if (shelf) {
      put(f, shelf.on ? 'it waited on the shelf' : 'it did not wait on the shelf', shelf.note);
    }
    put(f, 'how it reached the air', d.prov.prepared
      || (d.prov.how === 'live' ? 'made live, while you were listening' : d.prov.how));
    put(f, 'the shelf\u2019s last row (the station, not this line)',
      roomText(d.stages, 'shelf'));
    stage('shelf', 'the shelf', !!((shelf && shelf.on) || d.prov.how === 'shelf'),
      'The shelf is where a finished round waits for its turn. A round built '
      + 'ahead of time is taken off the shelf when the hour reaches it; a '
      + 'round made live never touches it.',
      f,
      (d.prov.how === 'live' || /live/.test(String(d.prov.prepared || '')))
        ? 'this line never sat on the shelf - it was made live, while you were '
          + 'listening'
        : 'the shelf holds no row for this line');

    /* 7. THE SCHEDULE - the hour's running order, and the scene it set. */
    f = [];
    if (d.scene) {
      put(f, 'the scene', String(d.scene.label || '')
        + (d.scene.road ? '  \u00b7  ' + String(d.scene.road) + ' road' : ''));
      put(f, 'set on', d.scene.where);
      if (Number(d.scene.since) > 0) {
        put(f, 'in force since', ago(now - Number(d.scene.since)));
      }
      putFold(f, 'the scene\u2019s brief', d.scene.brief);
    }
    put(f, 'this round', d.sched.kind);
    put(f, 'the round on the desk now', d.sched.kind_now
      ? String(d.sched.kind_now) + ' - a later entry, not this one' : '');
    if (d.place) {
      put(f, 'its place on the ledger', 'block ' + d.place.block + ', line ' + d.place.ord);
    }
    var led = flowAt(d.why, 'ledger');
    if (led) {
      put(f, 'the ledger says', String(led.label || '')
        + (led.detail ? ' - ' + String(led.detail) : ''));
    }
    stage('schedule', 'the schedule', !!(d.sched.kind || d.scene || d.place || led),
      'The schedule is the hour\u2019s running order: which road gets the next '
      + 'turn, in what scene, and where the line sits on the script ledger '
      + 'as block and line number.',
      f,
      'no schedule entry can be found for this line - it was minted outside '
      + 'a round');

    /* 8. ON AIR - the hand-over, and whether it was actually heard. */
    f = [];
    var aired = String((d.why && d.why.aired) || d.row.aired || '');
    var airAt = Number(d.row.air_at || 0);
    put(f, 'the row\u2019s state', aired
      ? aired + ' - ' + (ROADS[aired] || 'an output the page does not name') : '');
    var refused = ['withdrawn', 'held', 'failed', 'prepared', 'analysis']
      .indexOf(aired) >= 0;
    put(f, refused ? 'the slot it would have taken' : 'heard at', airAt
      ? clock(airAt) + (now > airAt ? '  (' + ago(now - airAt) + ')' : '  (yet to come)') : '');
    put(f, 'how long it ran', Number(d.row.seconds) > 0
      ? Number(d.row.seconds).toFixed(1) + ' s' : '');
    put(f, 'the page delivery', d.row.page_delivery);
    put(f, 'the delivery id', d.row.delivery_id);
    put(f, 'why it was refused', d.row.withdrawn_why);
    var hits = airHits(line, all);
    if (hits.read) {
      put(f, 'times in the 48-hour air log', String(hits.hits.length));
      if (hits.whens.length) put(f, 'last heard', ago(now - hits.whens[0]));
    }
    put(f, 'the last hand-off (the station, not this line)',
      roomText(d.stages, 'goes out'));
    stage('air', 'on air',
      !refused && !!(airAt
        || ['stream', 'box', 'both', 'airing', 'page', 'published'].indexOf(aired) >= 0),
      'On air is the last step: the row handed to an output - the stream, the '
      + 'box, the page - and the moment it was actually heard. A row can be '
      + 'refused here, in which case it was written and voiced and never went '
      + 'out.',
      f,
      refused
        ? 'this line was refused at hand-over and never went out - the row '
          + 'stands at “' + aired + '”, ' + (ROADS[aired] || 'kept off the air')
        : 'no air time is recorded for this line');

    return out;
  }

  /* ------------------------------------------ tapping a road on the strip */

  /* THE CAPTION IS NOW EIGHT BUTTONS, one under each dot. It still reads as
   * the same sentence - "the brief -> the writing room -> ..." - because the
   * arrows are kept between them, but every road is its own hit target with
   * its own name, which a canvas raycast could never give a screen reader or
   * a keyboard. */
  function stageBar(line, all, stages) {
    var bar = box && box.querySelector('.ld-flowwhy');
    if (!bar) return;
    bar.replaceChildren();
    stages.forEach(function (s, i) {
      if (i) bar.appendChild(make('i', 'ld-flowarrow', '\u2192'));
      var b = make('button', 'ld-stagebtn' + (s.got ? ' got' : ''), s.label);
      b.type = 'button';
      b.setAttribute('data-stage', s.key);
      b.setAttribute('aria-expanded', 'false');
      b.title = s.got ? 'what this road put into this line'
        : 'this road left no mark on this line';
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        pickStage(line, all, stages, s.key);
      });
      bar.appendChild(b);
    });
  }

  /* "I want to tap on THESE" - the dots themselves, not only their words.
   * The chain is drawn evenly spaced and centred on the canvas, so the
   * canvas is cut into one column per road and a tap lands in the column it
   * is over. The camera sways 1.3 world units out of 23.8, a twentieth of
   * the width, which is well inside a column half that wide: the dot under
   * the finger is the road that opens. */
  function canvasTaps(line, all, stages) {
    var canvas = box && box.querySelector('.ld-canvas');
    if (!canvas || !stages.length) return;
    canvas.style.cursor = 'pointer';
    canvas.addEventListener('click', function (e) {
      e.stopPropagation();
      var r = canvas.getBoundingClientRect();
      if (!r.width) return;
      var i = Math.floor(((e.clientX - r.left) / r.width) * stages.length);
      if (!(i >= 0)) i = 0;
      if (i >= stages.length) i = stages.length - 1;
      pickStage(line, all, stages, stages[i].key);
    });
  }

  function pickStage(line, all, stages, key) {
    openStage = (openStage === key) ? null : key;
    showStage(line, all, stages);
  }

  /* The panel, at the top of the SCROLLING body rather than in the fixed
   * strip: it reads as hanging off the chain of dots, it scrolls with
   * everything else, and the window cannot grow past the tablet's glass
   * however much the record has to say. */
  function showStage(line, all, stages) {
    var host = box && box.querySelector('.ld-stage-host');
    if (!host) return;
    host.replaceChildren();
    var bar = box.querySelector('.ld-flowwhy');
    if (bar) {
      Array.prototype.forEach.call(bar.querySelectorAll('.ld-stagebtn'), function (b) {
        var on = b.getAttribute('data-stage') === openStage;
        b.classList.toggle('open', on);
        b.setAttribute('aria-expanded', on ? 'true' : 'false');
      });
    }
    if (!openStage) return;
    var s = null;
    stages.forEach(function (x) { if (x.key === openStage) s = x; });
    if (!s) return;

    var panel = make('div', 'ld-stage' + (s.got ? '' : ' none'));
    var head = make('div', 'ld-stage-head');
    head.appendChild(make('b', '', s.label));
    head.appendChild(make('i', 'ld-stage-mark',
      s.got ? 'it left a mark on this line' : 'no mark on this line'));
    panel.appendChild(head);
    panel.appendChild(make('p', 'ld-stage-what', s.what));
    if (!s.got) panel.appendChild(make('p', 'ld-dim ld-stage-none', s.none));
    factsInto(panel, s.facts);
    host.appendChild(panel);
    try { panel.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
    catch (e) { /* an older webview scrolls or it does not */ }
  }

  /* 2026-09-14: "do a section above for admin options and show how each of
   * these options contributed to the current line ... how any pref or
   * modifier made it into the line." The station judges each desk dial
   * against this line's own paperwork (/api/dj/scenario `admin`): a green
   * dot is 'reached this line' with the proof in the how-line, red is
   * 'did not', grey is 'governs the station but is not traceable on one
   * line' - said as such rather than claimed. */
  function adminNode(all) {
    var rows = ((all.scene || {}).admin) || [];
    if (!rows.length) return null;
    var wrap = make('div', 'ld-admin');
    var applied = rows.filter(function (r) { return r.applied === true; });
    wrap.appendChild(make('p', 'ld-dim', applied.length
      + ' of ' + rows.length + ' options can be seen in this line\'s paperwork; the rest govern the station without a trace on one line'));
    var viewport = make('div', 'ld-admin-table-wrap');
    var table = make('table', 'ld-admin-table');
    var thead = document.createElement('thead');
    var headings = document.createElement('tr');
    ['Status', 'Option', 'Current value', 'Governs and evidence'].forEach(function (word) {
      headings.appendChild(make('th', '', word));
    });
    thead.appendChild(headings);
    table.appendChild(thead);
    var list = document.createElement('tbody');
    rows.forEach(function (r) {
      var state = r.applied === true ? 'on' : r.applied === false ? 'off' : 'na';
      var tr = document.createElement('tr');
      tr.className = 'ld-admin-row ' + state;
      tr.setAttribute('tabindex', '0');
      tr.setAttribute('role', 'button');
      tr.setAttribute('aria-expanded', 'false');
      var status = document.createElement('td');
      status.appendChild(make('i', 'ld-admin-dot', ''));
      status.appendChild(make('span', 'ld-admin-state',
        state === 'on' ? 'reached' : state === 'off' ? 'did not reach' : 'station-wide'));
      var name = document.createElement('td');
      name.appendChild(make('b', '', String(r.label || r.key || '')));
      var val = document.createElement('td');
      val.appendChild(make('div', 'ld-admin-cell-scroll',
        r.value === undefined || r.value === null ? '' : String(r.value)));
      var how = document.createElement('td');
      how.appendChild(make('div', 'ld-admin-cell-scroll',
        String(r.governs || '') + (r.how ? ' \u00b7 ' + r.how : '')));
      tr.appendChild(status); tr.appendChild(name); tr.appendChild(val); tr.appendChild(how);

      var detailRow = document.createElement('tr');
      detailRow.className = 'ld-admin-detail';
      detailRow.hidden = true;
      var detail = document.createElement('td');
      detail.colSpan = 4;
      var meta = r.edit || {};
      detail.appendChild(make('b', '', String(r.label || r.key || '')));
      detail.appendChild(make('p', 'ld-dim',
        'key: ' + String(r.key || '(not recorded)') + ' · '
        + (r.applied === true ? 'this value reached this line'
          : r.applied === false ? 'this value did not reach this line'
          : 'this governs the station but is not traceable on one line')));
      if (r.governs) detail.appendChild(make('p', '', String(r.governs)));
      if (r.how) detail.appendChild(make('p', 'ld-dim', String(r.how)));
      var full = make('pre', 'ld-pre ld-admin-full',
        meta.value === undefined || meta.value === null
          ? (r.value === undefined || r.value === null ? '' : String(r.value))
          : String(meta.value));
      detail.appendChild(editable(full, meta.scope ? {
        scope: String(meta.scope), key: String(meta.key || r.key || ''),
        label: String(meta.label || r.label || r.key || 'option'),
        how: String(meta.how || r.governs || ''),
        applies: meta.applies || ['future'],
        lineId: openFor ? String(openFor.id || '') : ''
      } : {scope: '', why: String(meta.why || READING_ONLY)}));
      detailRow.appendChild(detail);

      var toggle = function (ev) {
        if (ev && ev.type === 'keydown'
            && ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
        if (ev) ev.preventDefault();
        detailRow.hidden = !detailRow.hidden;
        tr.setAttribute('aria-expanded', detailRow.hidden ? 'false' : 'true');
      };
      tr.addEventListener('click', toggle);
      tr.addEventListener('keydown', toggle);
      list.appendChild(tr);
      list.appendChild(detailRow);
    });
    table.appendChild(list);
    viewport.appendChild(table);
    wrap.appendChild(viewport);
    return wrap;
  }

  function timesNode(line, all) {
    /* Counted in one place (#1149): the on-air road's panel quotes the same
     * numbers, and two readings of one log that disagree are worse than no
     * reading at all. */
    var got = airHits(line, all);
    var hits = got.hits;
    var wrap = make('div', '');
    if (!got.read) {
      wrap.appendChild(make('p', 'ld-wait',
        'the air log could not be read, so how often cannot be counted'));
      return wrap;
    }
    var now = Date.now() / 1000;
    var whens = got.whens;

    var list = make('ul', 'ld-facts');
    list.appendChild(fact('times in the last 48 hours', String(hits.length)
      + (hits.length === 1 ? ' — this one' : '')));
    if (whens.length) {
      list.appendChild(fact('last heard', ago(now - whens[0])));
      if (whens.length > 1) {
        var span = whens[0] - whens[whens.length - 1];
        var per = span > 0 ? (whens.length / (span / 3600)) : 0;
        list.appendChild(fact('how often',
          per >= 1 ? per.toFixed(1) + ' times an hour'
            : (per * 24).toFixed(1) + ' times a day'));
        list.appendChild(fact('first of these', ago(now - whens[whens.length - 1])));
      }
    }
    /* The air log keeps 48 hours; anything older is genuinely not here. */
    list.appendChild(fact('what this counts',
      'the station keeps 48 hours of air log, so this is that window'));
    wrap.appendChild(list);
    return wrap;
  }

  function fact(name, value) {
    var li = make('li', '');
    li.appendChild(make('b', '', name));
    li.appendChild(make('span', '', String(value)));
    return li;
  }

  /* THE HONEST ANSWER TO "WHY DOES IT KEEP COMING UP". Not a theory - the
   * worn cupboard counts how many separate lines carry each phrase, and
   * how many times the round holding it has aired. */
  function whyNode(line, all) {
    var worn = all.worn || {};
    var phrases = (worn.phrases || []).filter(function (p) {
      var ph = boiled(p.phrase);
      return ph && boiled(line.said).indexOf(ph) >= 0;
    });
    var rounds = (worn.rounds || []).filter(function (r) {
      var ph = boiled(r.phrase);
      return ph && boiled(line.said).indexOf(ph) >= 0;
    });
    var wrap = make('div', '');
    if (!phrases.length && !rounds.length) {
      wrap.appendChild(make('p', 'ld-dim',
        'nothing in this line is on the station’s worn list - it is not '
        + 'repeating for a phrase it has overused.'));
      if (typeof worn.threshold === 'number') {
        wrap.appendChild(make('p', 'ld-dim',
          'the worn list counts a phrase once it appears in '
          + worn.threshold + ' or more separate lines.'));
      }
      return wrap;
    }
    var list = make('ul', 'ld-facts');
    phrases.slice(0, 4).forEach(function (p) {
      list.appendChild(fact('“' + p.phrase + '”',
        'said in ' + p.said_in_lines + ' separate lines'));
    });
    rounds.slice(0, 4).forEach(function (r) {
      list.appendChild(fact(String(r.label || r.road || 'the round holding it'),
        'aired ' + (r.aired || 0) + ' time' + (r.aired === 1 ? '' : 's')));
    });
    wrap.appendChild(list);
    wrap.appendChild(make('p', 'ld-dim',
      'A phrase on this list is why a line comes round again: the writing '
      + 'room reaches for it, and the banked rounds carrying it keep their '
      + 'turn. Retiring one of those rounds is the cure, below.'));
    return wrap;
  }

  function wroteNode(all) {
    var prov = all.prov;
    if (!prov) {
      var gone = make('p', 'ld-dim',
        'The booth keeps the paperwork for its last 240 lines and this one '
        + 'is past that, so the room that wrote it can no longer be asked. '
        + 'Everything else on this page is still true.');
      return gone;
    }
    var written = prov.written || {};
    var render = prov.render || {};
    var sched = prov.schedule || {};
    var wrap = make('div', '');
    if (prov.brief || prov.segment || sched.prompt) {
      wrap.appendChild(make('p', '', String(prov.brief || prov.segment || sched.prompt)));
    }
    [['the prompt as sent', written.prompt || prov.prompt],
      ['what came back', written.script || prov.script || prov.script_plain],
      ['after the tint', written.tinted || prov.script_tinted]].forEach(function (pair) {
      if (!pair[1]) return;
      var d = make('details', 'ld-fold');
      d.appendChild(make('summary', '', pair[0]));
      /* [#1231] Two of these three are the round itself. The tint pass
       * writes its rewrite back over entry["script"] (app.py, the tint
       * road), so the dressed clause IS what the round now holds and
       * editing it is editing the round. The prompt as sent is a record
       * of one visit to the writing room and says so. */
      d.appendChild(editable(make('pre', 'ld-pre', String(pair[1])),
        pair[0] === 'the prompt as sent'
          ? {scope: '', why: 'the prompt as sent is the record of one '
              + 'visit to the writing room and cannot be rewritten after '
              + 'the fact. What shapes the NEXT one is on the scene sheet '
              + 'at the top of this window: the road system prompt, the '
              + 'seat character and the station disposition - all three '
              + 'can be typed in.'}
          : {scope: 'script', key: '',
             label: pair[0] === 'after the tint'
               ? 'the dressed clause' : 'the round as it was written',
             how: 'change ONE line and Save - a round that has aired is '
               + 'copied, the kept one is untouched, and only the line '
               + 'you changed re-records',
             applies: ['round'],
             lineId: openFor ? String(openFor.id || '') : ''}));
      wrap.appendChild(d);
    });
    var bits = [];
    if (written.model || prov.model) bits.push(String(written.model || prov.model));
    if (render.engine || prov.engine) bits.push(String(render.engine || prov.engine));
    if (Number(written.ms) > 0) bits.push(millis(written.ms));
    if (bits.length) wrap.appendChild(make('i', 'ld-dim', bits.join('  ·  ')));
    return wrap.children.length ? wrap : null;
  }

  /* "Examine what chunk caused it to be said" - the passages and documents
   * the writer was actually looking at. */
  function shownNode(all) {
    var prov = all.prov;
    if (!prov) return null;
    var shards = prov.shards || prov.crystal || [];
    var docs = prov.documents || prov.sources || [];
    var vectors = prov.vectors || prov.searches || [];
    if (!shards.length && !docs.length && !vectors.length) return null;
    var wrap = make('div', '');

    shards.forEach(function (s) {
      var d = make('details', 'ld-fold');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(s.crystal || s.name || 'a passage')));
      sum.appendChild(make('i', '', String(s.file || '')
        + (s.in_prompt ? '  ·  in the prompt' : '  ·  not used')));
      d.appendChild(sum);
      d.appendChild(crystalEvidence(s, 'shard'));
      wrap.appendChild(d);
    });
    docs.forEach(function (doc) {
      var d = make('details', 'ld-fold');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(doc.title || doc.file || 'a document')));
      sum.appendChild(make('i', '', doc.quoted ? 'quoted' : 'read, not quoted'));
      d.appendChild(sum);
      d.appendChild(crystalEvidence(doc, 'document'));
      wrap.appendChild(d);
    });
    if (vectors.length) {
      wrap.appendChild(make('h5', '', 'what it searched for'));
      vectors.forEach(function (v) {
        var d = make('details', 'ld-fold ld-crystal-fold');
        d.appendChild(make('summary', '', String(v.query || v.q || 'search')));
        d.appendChild(crystalEvidence(v, 'vector'));
        wrap.appendChild(d);
      });
    }
    return wrap;
  }

  function roadNode(all) {
    var stages = (all.road || {}).stages || [];
    if (!stages.length) return null;
    var list = make('ol', 'ld-steps');
    stages.forEach(function (st) {
      var li = make('li', st.seen ? '' : 'unseen');
      li.appendChild(make('b', '', String(st.label || '')));
      if (st.seen && st.text) li.appendChild(make('p', 'ld-dim', String(st.text)));
      list.appendChild(li);
    });
    return list;
  }

  /* NOTHING IS DELETED HERE, and the button says so.
   *
   * The station's own contract (app.py:99772): worn/review marks a round
   * PENDING on the retirement desk with a reason and returns False - "the
   * operator has not answered yet" - and the round keeps airing until he
   * answers. A button here that claimed to delete would be lying about
   * what the station does. */
  function retireNode(line, all) {
    var worn = all.worn || {};
    var rounds = (worn.rounds || []).filter(function (r) {
      var ph = boiled(r.phrase);
      return ph && boiled(line.said).indexOf(ph) >= 0;
    });
    var wrap = make('div', '');
    if (!rounds.length) {
      wrap.appendChild(make('p', 'ld-dim',
        'This line is not held in a banked round the station has flagged '
        + 'as worn, so there is nothing here to retire.'));
      return wrap;
    }
    wrap.appendChild(make('p', 'ld-dim',
      'This puts the round carrying it up on the retirement desk with a '
      + 'reason. NOTHING IS DELETED: it keeps airing until you answer the '
      + 'desk, which is the station’s own rule, not this screen’s.'));
    rounds.slice(0, 3).forEach(function (r) {
      var row = make('button', 'ld-retire');
      row.type = 'button';
      row.appendChild(make('b', '', 'Put up: ' + String(r.label || r.road || r.id)));
      row.appendChild(make('i', '', 'aired ' + (r.aired || 0) + ' times'));
      var note = make('span', 'ld-note');
      row.appendChild(note);
      row.addEventListener('click', function (event) {
        event.stopPropagation();
        row.disabled = true;
        note.textContent = 'putting it up…';
        api().post('/api/cupboard/worn/review', {ids: [r.id]}).then(function (got) {
          note.textContent = String((got && got.say)
            || 'on the retirement desk — answer it there');
          row.disabled = false;
        }, function (err) {
          note.textContent = 'the station refused: '
            + ((err && err.message) || err);
          note.classList.add('bad');
          row.disabled = false;
        });
      });
      wrap.appendChild(row);
    });
    return wrap;
  }

  /* -------------------------------------------------------------- the 3D */

  /* The path as a chain, with the stations it actually reached lit. It
   * drifts rather than orbits: this is a diagram that happens to have
   * depth, and a diagram that spins is a diagram you cannot read. */
  function drawFlow(canvas, steps) {
    return three().then(function (THREE) {
      if (!THREE || !steps.length) return null;
      var renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true,
        alpha: true});
      renderer.setPixelRatio(Math.min(2, root.devicePixelRatio || 1));
      var w = canvas.clientWidth || 320;
      var h = canvas.clientHeight || 150;
      renderer.setSize(w, h, false);

      var view = new THREE.Scene();
      var camera = new THREE.PerspectiveCamera(46, w / h, 0.1, 200);
      var span = Math.max(1, steps.length - 1);
      var step = 3.4;
      var left = -(span * step) / 2;

      var balls = [];
      steps.forEach(function (s, i) {
        var geo = new THREE.SphereGeometry(s.got ? 0.6 : 0.4, 18, 14);
        var mat = new THREE.MeshBasicMaterial({
          color: s.got ? 0x65c7da : 0x35414c,
          transparent: true, opacity: s.got ? 0.95 : 0.4
        });
        var ball = new THREE.Mesh(geo, mat);
        ball.position.set(left + i * step, 0, 0);
        view.add(ball);
        balls.push(ball);
        if (i > 0) {
          var line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([
              new THREE.Vector3(left + (i - 1) * step, 0, 0),
              new THREE.Vector3(left + i * step, 0, 0)]),
            new THREE.LineBasicMaterial({
              color: s.got ? 0x54d18b : 0x35414c,
              transparent: true, opacity: s.got ? 0.7 : 0.22}));
          view.add(line);
        }
      });

      /* A packet travelling the part of the road the line actually took. */
      var reach = steps.filter(function (s) { return s.got; }).length - 1;
      var packet = new THREE.Mesh(
        new THREE.SphereGeometry(0.17, 10, 8),
        new THREE.MeshBasicMaterial({color: 0xffffff}));
      view.add(packet);

      camera.position.set(0, 2.2, Math.max(11, span * 2.3));
      camera.lookAt(0, 0, 0);

      var raf = 0;
      var alive = true;
      var t0 = performance.now();
      function frame() {
        if (!alive) return;
        raf = requestAnimationFrame(frame);
        var t = (performance.now() - t0) / 1000;
        var travel = (t * 0.42) % 1;
        packet.position.set(left + travel * Math.max(0, reach) * step,
          Math.sin(travel * Math.PI) * 0.42, 0);
        packet.visible = reach > 0;
        camera.position.x = Math.sin(t * 0.16) * 1.3;
        camera.lookAt(0, 0, 0);
        renderer.render(view, camera);
      }
      frame();

      return {stop: function () {
        alive = false;
        cancelAnimationFrame(raf);
        try { renderer.dispose(); } catch (e) { /* gone */ }
      }};
    }, function () { return null; });
  }

  /* [#1231] busy(): a field on this sheet is dirty or holds the caret.
   * Anything that would repaint over the top asks first. */
  root.PineLineDeep = {open: open, close: close, busy: editsBusy};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineLineDeep;
    module.exports._test = {stageFacts: stageFacts, crystalEvidence: crystalEvidence,
      factsInto: factsInto, shownNode: shownNode};
  }
})(typeof window !== 'undefined' ? window : globalThis);
