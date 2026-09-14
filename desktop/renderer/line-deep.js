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

  /* ------------------------------------------------------------ the shell */

  function close() {
    if (scene && scene.stop) { try { scene.stop(); } catch (e) { /* gone */ } }
    scene = null;
    openFor = null;
    if (box) { box.remove(); box = null; }
  }

  function open(line) {
    close();
    openFor = line;
    box = make('div', 'ld-box');
    box.innerHTML =
      '<div class="ld-head">'
      + '<b>How this line came to be</b>'
      + '<button class="ld-close" type="button" aria-label="close">×</button>'
      + '</div>'
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
    box.querySelector('.ld-said').textContent = String(line.said || '').slice(0, 300);
    box.querySelector('.ld-close').addEventListener('click', function (e) {
      e.stopPropagation();
      close();
    });
    if (root.PineDismiss) root.PineDismiss.watch(box, close, []);

    var body = box.querySelector('.ld-body');
    body.appendChild(make('p', 'ld-wait', 'asking the station…'));
    gather(line).then(function (all) {
      if (!box) return;
      paint(line, all);
    }, function (err) {
      if (!box) return;
      sceneRow(line, null);
      body.replaceChildren();
      body.appendChild(make('p', 'ld-wait',
        'the station could not say: ' + ((err && err.message) || err)));
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
      soft(api().get('/api/dj/scenario?line=' + encodeURIComponent(line.id || '')))
    ]).then(function (got) {
      return {prov: got[0], road: got[1], worn: got[2], air: got[3], scene: got[4]};
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
    var body = box.querySelector('.ld-body');
    body.replaceChildren();

    var steps = stepsOf(all);
    drawFlow(box.querySelector('.ld-canvas'), steps).then(function (made) {
      scene = made;
      if (!made) box.querySelector('.ld-flow').classList.add('flat');
    }, function () { scene = null; });
    box.querySelector('.ld-flowwhy').textContent =
      steps.map(function (s) { return s.label; }).join('  →  ');

    sceneRow(line, all.scene);

    section(body, 'how often it has gone out', timesNode(line, all));
    section(body, 'why it keeps coming up', whyNode(line, all));
    section(body, 'the room that wrote it', wroteNode(all));
    section(body, 'what it was shown', shownNode(all));
    section(body, 'the road, step by step', roadNode(all));
    section(body, 'if you never want to hear it again', retireNode(line, all));
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
    if (i.value) {
      card.appendChild(make('p', 'ld-scene-value', String(i.value)));
    } else if (!i.on) {
      card.appendChild(make('p', 'ld-scene-value ld-dim', 'nothing set'));
    }
    if (i.detail) {
      var d = make('details', 'ld-fold');
      d.appendChild(make('summary', '', 'the whole of it'));
      d.appendChild(make('pre', 'ld-pre', String(i.detail)));
      card.appendChild(d);
    }
    if (i.why) card.appendChild(make('p', 'ld-scene-why', String(i.why)));
    if (i.desk) {
      card.appendChild(make('span', 'ld-scene-desk',
        'manage on the ' + String(i.desk) + ' desk'));
    }
    return card;
  }

  /* The path, as stations. Each one knows whether it was REACHED, which is
   * what makes the diagram worth drawing rather than decorative. */
  function stepsOf(all) {
    var prov = all.prov || {};
    var road = all.road || {};
    var stages = road.stages || [];
    function seen(name) {
      return stages.some(function (s) {
        return s.seen && String(s.label || '').toLowerCase().indexOf(name) >= 0;
      });
    }
    return [
      {label: 'the brief', got: !!(prov.brief || prov.segment || prov.schedule)},
      {label: 'the writing room', got: !!(prov.prompt || prov.script)},
      {label: 'the crystal', got: !!((prov.shards || prov.crystal || []).length)},
      {label: 'the tint', got: !!(prov.tinted || prov.script_tinted)},
      {label: 'the recording room', got: seen('engine') || seen('rendered')},
      {label: 'the shelf', got: seen('shelf')},
      {label: 'the schedule', got: !!(prov.schedule || prov.slot)},
      {label: 'on air', got: true}
    ];
  }

  function timesNode(line, all) {
    var rows = ((all.air || {}).rows || (all.air || {}).entries || [])
      .filter(function (r) { return r && (r.text || r.id); });
    var mine = boiled(line.said);
    var hits = rows.filter(function (r) {
      if (r.id && String(r.id) === line.id) return true;
      var t = boiled(r.text);
      return t && mine && (t === mine || (mine.length > 30 && t.indexOf(mine.slice(0, 30)) >= 0));
    });
    var wrap = make('div', '');
    if (!rows.length) {
      wrap.appendChild(make('p', 'ld-wait',
        'the air log could not be read, so how often cannot be counted'));
      return wrap;
    }
    var now = Date.now() / 1000;
    var whens = hits.map(function (r) { return Number(r.at || r.ts || 0); })
      .filter(Boolean).sort(function (a, b) { return b - a; });

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
    var wrap = make('div', '');
    if (prov.brief || prov.segment) {
      wrap.appendChild(make('p', '', String(prov.brief || prov.segment)));
    }
    [['the prompt as sent', prov.prompt],
      ['what came back', prov.script || prov.script_plain],
      ['after the tint', prov.script_tinted]].forEach(function (pair) {
      if (!pair[1]) return;
      var d = make('details', 'ld-fold');
      d.appendChild(make('summary', '', pair[0]));
      d.appendChild(make('pre', 'ld-pre', String(pair[1])));
      wrap.appendChild(d);
    });
    var bits = [];
    if (prov.model) bits.push(String(prov.model));
    if (prov.engine) bits.push(String(prov.engine));
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

    shards.slice(0, 6).forEach(function (s) {
      var d = make('details', 'ld-fold');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(s.crystal || s.name || 'a passage')));
      sum.appendChild(make('i', '', String(s.file || '')
        + (s.in_prompt ? '  ·  in the prompt' : '  ·  not used')));
      d.appendChild(sum);
      d.appendChild(make('pre', 'ld-pre', String(s.text || '')));
      wrap.appendChild(d);
    });
    docs.slice(0, 6).forEach(function (doc) {
      var d = make('details', 'ld-fold');
      var sum = make('summary', '');
      sum.appendChild(make('b', '', String(doc.title || doc.file || 'a document')));
      sum.appendChild(make('i', '', doc.quoted ? 'quoted' : 'read, not quoted'));
      d.appendChild(sum);
      d.appendChild(make('pre', 'ld-pre', String(doc.text || doc.snippet || '')));
      wrap.appendChild(d);
    });
    if (vectors.length) {
      wrap.appendChild(make('h5', '', 'what it searched for'));
      var list = make('ul', 'ld-facts');
      vectors.slice(0, 6).forEach(function (v) {
        list.appendChild(fact(String(v.query || v.q || '—'),
          String(v.hits || v.count || '')));
      });
      wrap.appendChild(list);
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

  root.PineLineDeep = {open: open, close: close};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineLineDeep;
  }
})(typeof window !== 'undefined' ? window : globalThis);
