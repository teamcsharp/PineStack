/* #1226: THE SEGMENTS, THEIR PROMPTS, AND A WAY TO PUT A STORY ON THE AIR.
 *
 * "I want a section for segments and I want to expand it and be able to see
 *  every segment that's being scheduled and how it's being listed, and I want
 *  to be able to click on it and modify the system prompts and add different
 *  system prompts and try different system prompts for each section based on
 *  how it's constructed... I want to be able to go between system prompts and
 *  modify each segment as they are being created... I also want to be able to
 *  contribute scenarios that become part of the air through this window. I want
 *  a + that allows me to add topics that become part of the randomized banter."
 *
 * And: "I want to be able to drag and drop markdowns... onto the orchestrator
 * and have it pop up a topic window where I can set up scenarios like this to
 * take place over the next 5-10 hours as a plotline."
 *
 * NOTHING HERE IS NEW MACHINERY. Every one of these already existed on the
 * station and had no way in from this window:
 *
 *   GET/POST /api/schedule/prompts   per-kind shelves, each with variants and
 *                                    an `active` index. The route's own words:
 *                                    "Used IMMEDIATELY: the entry on air
 *                                    re-reads its prompt on the very next
 *                                    round, not at the next restart."
 *   GET/POST /api/dj/topics          the banter bank, 242 rows when this was
 *                                    written
 *   GET/POST /api/dj/plots           plotlines with acts, span_minutes (capped
 *                                    at 2880 - forty-eight hours, so his
 *                                    "5-10 hours" sits comfortably inside),
 *                                    act_marks and a running `so_far`
 *   POST /api/dj/plots/{id}/activate
 *
 * So this is a way in, not an invention. The one rule it holds to is that a
 * write is never guessed: the shelf is read, the one field that changed is
 * changed, and the whole shelf goes back - because POST /api/schedule/prompts
 * replaces a kind's shelf entirely, and sending a partial one would delete the
 * variants he spent an evening writing.
 */
(function (root) {
  'use strict';
  if (root.PineSegments) return;

  var KINDS_SAID = {
    news: 'News bulletin', gallery: 'Painting sale', caller: 'Phone call',
    manager: 'Memo from upstairs', ad: 'Advert', banter: 'Banter',
    banter_caller: 'Banter with a caller', track_talk: 'Track talk',
    record: 'The record', recap: 'Recap', deep: 'Deep cut',
    bombshell: 'Bombshell', guest: 'Guest'
  };

  function el(tag, cls, text) {
    var n = root.document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== null && typeof text !== 'undefined') n.textContent = String(text);
    return n;
  }

  /* Same split every view in this directory carries: the desk is a file://
     document and talks through the bridge, the tablet is served by the station
     and a bare path is right. */
  function where() {
    try { if (root.PINE_BASE) return String(root.PINE_BASE); } catch (err) { /* none */ }
    try {
      if (root.location && /^https?:/.test(root.location.protocol)) return '';
    } catch (err) { /* none */ }
    return 'http://10.89.1.246:8096';
  }
  function key() {
    try { return root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || ''; }
    catch (err) { return ''; }
  }
  function head(json) {
    var h = {};
    if (key()) h.Authorization = 'Bearer ' + key();
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }
  function get(path) {
    try {
      if (root.pineDesktop && root.pineDesktop.get) return root.pineDesktop.get(path);
    } catch (err) { /* fall through */ }
    return root.fetch(where() + path, {headers: head(false), cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; });
  }
  function send(method, path, body) {
    try {
      if (root.pineDesktop && root.pineDesktop.post && method === 'POST') {
        return root.pineDesktop.post(path, body || {});
      }
    } catch (err) { /* fall through */ }
    return root.fetch(where() + path, {
      method: method, headers: head(true), cache: 'no-store',
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) { return r.ok ? r.json() : null; });
  }

  /* ------------------------------------------------------- the segments pane */

  var shelves = null;          /* the whole /api/schedule/prompts payload */

  function armedOf(blob) {
    var vs = (blob && blob.variants) || [];
    var i = Math.max(0, Math.min(vs.length - 1, Number(blob && blob.active) || 0));
    return vs[i] || null;
  }

  /* A WRITE IS NEVER A GUESS. POST /api/schedule/prompts replaces the whole
     shelf for a kind, so the shelf we hold is edited and sent back entire.
     Sending only the field that moved would delete every other variant. */
  function saveKind(kind, mutate, done) {
    get('/api/schedule/prompts').then(function (all) {
      var blob = (all && all[kind]) || {active: 0, variants: []};
      var next = mutate(JSON.parse(JSON.stringify(blob)));
      if (!next || !(next.variants || []).length) { if (done) done(false, 'nothing to save'); return; }
      var payload = {};
      payload[kind] = next;
      send('POST', '/api/schedule/prompts', payload).then(function (ok) {
        if (all) { all[kind] = next; shelves = all; }
        if (done) done(!!ok, ok ? '' : 'the station refused the write');
      })['catch'](function () { if (done) done(false, 'the station could not be reached'); });
    })['catch'](function () { if (done) done(false, 'could not read the shelf back'); });
  }

  function variantRow(kind, blob, index, redraw) {
    var vs = blob.variants || [];
    var v = vs[index];
    var armed = index === Math.max(0, Math.min(vs.length - 1, Number(blob.active) || 0));
    var wrap = el('div', 'pseg-var' + (armed ? ' on' : ''));

    var top = el('div', 'pseg-var-top');
    var pick = el('button', 'pseg-arm', armed ? 'on air' : 'use this');
    pick.setAttribute('type', 'button');
    pick.disabled = armed;
    pick.addEventListener('click', function () {
      pick.disabled = true;
      pick.textContent = 'arming...';
      saveKind(kind, function (b) { b.active = index; return b; }, function (ok, why) {
        if (!ok) { pick.disabled = false; pick.textContent = 'use this'; note(wrap, why); return; }
        redraw();
      });
    });
    top.appendChild(pick);
    top.appendChild(el('span', 'pseg-var-name', v.name || 'Untitled'));
    wrap.appendChild(top);

    var box = el('textarea', 'pseg-text');
    box.value = String(v.text || '');
    box.setAttribute('rows', '5');
    box.setAttribute('spellcheck', 'false');
    box.setAttribute('aria-label', (v.name || 'prompt') + ' text');
    wrap.appendChild(box);

    var bar = el('div', 'pseg-bar');
    var save = el('button', 'pseg-save', 'Save this prompt');
    save.setAttribute('type', 'button');
    save.addEventListener('click', function () {
      save.disabled = true;
      save.textContent = 'saving...';
      saveKind(kind, function (b) {
        if (b.variants[index]) b.variants[index].text = box.value;
        return b;
      }, function (ok, why) {
        save.disabled = false;
        save.textContent = 'Save this prompt';
        note(wrap, ok ? 'saved - the next round of this segment uses it' : why);
      });
    });
    bar.appendChild(save);
    wrap.appendChild(bar);
    return wrap;
  }

  function note(host, text) {
    if (!text) return;
    var old = host.querySelector('.pseg-note');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    host.appendChild(el('div', 'pseg-note', text));
  }

  function kindBlock(kind, blob, redraw) {
    var wrap = el('div', 'pseg-kind');
    var head_ = el('button', 'pseg-kind-head');
    head_.setAttribute('type', 'button');
    head_.appendChild(el('span', 'pseg-kind-name', KINDS_SAID[kind] || kind));
    var armed = armedOf(blob);
    head_.appendChild(el('span', 'pseg-kind-sum',
      (armed ? (armed.name || 'Untitled') : 'no prompt') + '  ·  '
      + ((blob.variants || []).length) + ' to choose from'));
    wrap.appendChild(head_);

    var body = el('div', 'pseg-kind-body');
    body.hidden = true;
    wrap.appendChild(body);

    head_.addEventListener('click', function () {
      body.hidden = !body.hidden;
      wrap.classList.toggle('open', !body.hidden);
      if (body.hidden || body.children.length) return;
      var vs = blob.variants || [];
      for (var i = 0; i < vs.length; i += 1) {
        body.appendChild(variantRow(kind, blob, i, redraw));
      }
      var add = el('button', 'pseg-add', '+ another prompt to try');
      add.setAttribute('type', 'button');
      add.addEventListener('click', function () {
        add.disabled = true;
        saveKind(kind, function (b) {
          b.variants.push({
            id: 'pv-' + String(Date.now()).slice(-8) + String(b.variants.length),
            name: 'A new way of doing ' + (KINDS_SAID[kind] || kind),
            text: (armedOf(b) || {}).text || ''
          });
          b.active = b.variants.length - 1;   /* try it at once - that is the point */
          return b;
        }, function (ok, why) {
          add.disabled = false;
          if (ok) redraw(); else note(body, why);
        });
      });
      body.appendChild(add);
    });
    return wrap;
  }

  function pane(host) {
    host.textContent = '';
    var mount = el('div', 'pseg-wrap');
    host.appendChild(mount);
    mount.appendChild(el('div', 'pseg-loading', 'reading the prompt shelves...'));

    function redraw() {
      get('/api/schedule/prompts').then(function (all) {
        shelves = all || {};
        mount.textContent = '';
        var kinds = Object.keys(shelves).sort();
        if (!kinds.length) {
          mount.appendChild(el('div', 'pseg-loading',
            'the station published no prompt shelves'));
          return;
        }
        mount.appendChild(el('div', 'pseg-lead',
          'Every segment the running order can call, and the system prompt each '
          + 'one is written against. A prompt you arm here is used IMMEDIATELY - '
          + 'the next round of that segment reads it, without a restart.'));
        for (var i = 0; i < kinds.length; i += 1) {
          mount.appendChild(kindBlock(kinds[i], shelves[kinds[i]], redraw));
        }
        mount.appendChild(topicsBlock());
      })['catch'](function () {
        mount.textContent = '';
        mount.appendChild(el('div', 'pseg-note', 'the station did not answer'));
      });
    }
    redraw();
  }

  /* ----------------------------------------------------------- the topics + */

  function topicsBlock(options) {
    options = options || {};
    var next = !!options.next;
    var history = !!options.history;
    var wrap = el('div', 'pseg-kind pseg-topics');
    var head_ = el('div', 'pseg-kind-head pseg-static');
    head_.appendChild(el('span', 'pseg-kind-name',
      next ? 'Next banter scenario' : 'Topics for the banter'));
    var sum = el('span', 'pseg-kind-sum', 'counting...');
    head_.appendChild(sum);
    wrap.appendChild(head_);

    var row = el('div', 'pseg-topic-row');
    var input = el('input', 'pseg-topic-in');
    input.type = 'text';
    input.placeholder = next ? 'Describe the scenario...' : 'Something for them to get into...';
    input.setAttribute('aria-label', next
      ? 'The scenario for the next banter round' : 'A new topic for the banter');
    var plus = el('button', 'pseg-plus' + (next ? ' pseg-next' : ''),
      next ? 'Queue next' : '+');
    plus.setAttribute('type', 'button');
    plus.setAttribute('title', next
      ? 'Save this scenario and queue it for the next banter round'
      : 'Add this to the banter bank');

    function add() {
      var text = String(input.value || '').trim();
      if (!text) return;
      plus.disabled = true;
      send('POST', '/api/dj/topics', {text: text, kind: 'topic', next: next})
        .then(function (ok) {
          plus.disabled = false;
          if (!ok) { note(wrap, 'the station refused it'); return; }
          input.value = '';
          note(wrap, next && ok.queued
            ? 'saved and queued for the next banter round'
            : 'in the bank - it can come up in the banter from here on');
          count();
          if (history) loadHistory();
        })['catch'](function () { plus.disabled = false; note(wrap, 'could not reach the station'); });
    }
    plus.addEventListener('click', add);
    input.addEventListener('keydown', function (ev) {
      if (ev && ev.key === 'Enter') { ev.preventDefault(); add(); }
    });
    row.appendChild(input);
    row.appendChild(plus);
    wrap.appendChild(row);

    var prior = null;

    function iconButton(cls, icon, label) {
      var b = el('button', cls);
      b.type = 'button';
      b.title = label;
      b.setAttribute('aria-label', label);
      try {
        b.innerHTML = typeof root.pineIcon === 'function' ? root.pineIcon(icon, label) : '';
      } catch (err) { b.innerHTML = ''; }
      if (!b.innerHTML) b.textContent = label;
      return b;
    }

    function actOn(saved, verb, button) {
      if (!saved || !saved.id) return;
      button.disabled = true;
      send('POST', '/api/dj/topics/' + encodeURIComponent(saved.id) + '/' + verb, {})
        .then(function (got) {
          button.disabled = false;
          if (!got) { note(wrap, 'the station refused that scenario'); return; }
          note(wrap, verb === 'drop'
            ? 'the scenario is being written into the current broadcast'
            : 'that scenario is next in the banter queue');
          loadHistory();
        })['catch'](function () {
          button.disabled = false;
          note(wrap, 'could not reach the station');
        });
    }

    function paintHistory(rows) {
      if (!prior) return;
      prior.replaceChildren();
      rows.forEach(function (saved) {
        var item = el('div', 'pseg-topic-item');
        var words = el('button', 'pseg-topic-words', saved.text || 'Untitled scenario');
        words.type = 'button';
        words.title = 'Put this scenario in the editor';
        words.addEventListener('click', function () {
          input.value = String(saved.text || '');
          input.focus();
        });
        var meta = el('span', 'pseg-topic-meta', String(Number(saved.used) || 0) + ' uses');
        var queue = iconButton('pseg-topic-action', 'c:add', 'Queue this scenario next');
        var now = iconButton('pseg-topic-action', 'c:play--filled-alt', 'Use this scenario now');
        queue.addEventListener('click', function () { actOn(saved, 'queue', queue); });
        now.addEventListener('click', function () { actOn(saved, 'drop', now); });
        item.appendChild(words);
        item.appendChild(meta);
        item.appendChild(queue);
        item.appendChild(now);
        prior.appendChild(item);
      });
    }

    function loadHistory() {
      if (!prior) return Promise.resolve();
      return get('/api/dj/topics').then(function (got) {
        var rows = (got && (got.topics || got.rows)) || [];
        sum.textContent = rows.length + ' in the bank';
        paintHistory(rows.slice(0, 150));
      })['catch'](function () { note(wrap, 'the saved scenarios could not be read'); });
    }

    if (history) {
      wrap.appendChild(el('div', 'pseg-topic-prior-title', 'Previous topics'));
      prior = el('div', 'pseg-topic-list');
      wrap.appendChild(prior);
    }

    function count() {
      get('/api/dj/topics').then(function (got) {
        var rows = (got && (got.topics || got.rows)) || [];
        sum.textContent = rows.length + ' in the bank';
      })['catch'](function () { sum.textContent = 'could not be counted'; });
    }
    if (history) loadHistory(); else count();
    return wrap;
  }

  var topicSheet = null;

  function topicShut() {
    if (topicSheet && topicSheet.parentNode) topicSheet.parentNode.removeChild(topicSheet);
    topicSheet = null;
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function topicWindow() {
    if (topicSheet && topicSheet.parentNode) return topicSheet;
    var node = el('div', 'pseg-sheet pseg-topic-sheet');
    node.setAttribute('role', 'dialog');
    node.setAttribute('aria-modal', 'false');
    node.setAttribute('data-pine-drag', '');
    var top = el('div', 'pseg-sheet-top');
    top.setAttribute('data-pine-drag-handle', '');
    top.appendChild(el('span', 'pseg-sheet-t', 'Things to spring on them'));
    var x = el('button', 'pseg-x', 'x');
    x.setAttribute('type', 'button');
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', topicShut);
    top.appendChild(x);
    node.appendChild(top);
    node.appendChild(topicsBlock({next: true, history: true}));
    root.document.body.appendChild(node);
    topicSheet = node;
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
    try { node.querySelector('.pseg-topic-in').focus(); } catch (err) { /* optional */ }
    return node;
  }

  /* ------------------------------------------- a markdown becomes a plotline */

  /* Turn a document into a title and a run of acts. A heading run is preferred
     because that is how a written piece is already divided; failing that, the
     blank lines are the author's own paragraphing and are the next best guess.
     The API caps acts at 24 and each at 600 characters, so this caps to match
     rather than letting the server silently truncate his story. */
  function readMarkdown(text, filename) {
    var lines = String(text || '').split(/\r?\n/);
    var title = '';
    var i;
    for (i = 0; i < lines.length; i += 1) {
      var m = /^#\s+(.+?)\s*$/.exec(lines[i]);
      if (m) { title = m[1]; break; }
    }
    if (!title) {
      for (i = 0; i < lines.length; i += 1) {
        if (String(lines[i]).trim()) { title = String(lines[i]).trim(); break; }
      }
    }
    title = (title || String(filename || 'A dropped story')).replace(/^#+\s*/, '').slice(0, 120);

    var acts = [], current = null;
    for (i = 0; i < lines.length; i += 1) {
      var h = /^#{2,3}\s+(.+?)\s*$/.exec(lines[i]);
      if (h) {
        if (current) acts.push(current);
        current = h[1];
        continue;
      }
      if (current && String(lines[i]).trim() && current.length < 560) {
        current += ' - ' + String(lines[i]).trim();
      }
    }
    if (current) acts.push(current);
    if (!acts.length) {
      acts = String(text || '').split(/\n\s*\n/).map(function (p) {
        return p.replace(/\s+/g, ' ').trim();
      }).filter(Boolean);
    }
    acts = acts.map(function (a) { return String(a).slice(0, 600); }).slice(0, 24);
    return {title: title, acts: acts};
  }

  var plotSheet = null;

  function plotWindow(parsed) {
    if (plotSheet && plotSheet.parentNode) plotSheet.parentNode.removeChild(plotSheet);
    var node = el('div', 'pseg-sheet');
    node.setAttribute('role', 'dialog');
    node.setAttribute('data-pine-drag', '');

    var top = el('div', 'pseg-sheet-top');
    top.setAttribute('data-pine-drag-handle', '');
    top.appendChild(el('span', 'pseg-sheet-t', 'Put this on the air as a plotline'));
    var x = el('button', 'pseg-x', 'x');
    x.setAttribute('type', 'button');
    x.addEventListener('click', function () { shut(); });
    top.appendChild(x);
    node.appendChild(top);

    var name = el('input', 'pseg-title-in');
    name.type = 'text';
    name.value = parsed.title;
    name.setAttribute('aria-label', 'The plotline title');
    node.appendChild(name);

    node.appendChild(el('div', 'pseg-sheet-sub',
      parsed.acts.length + ' act(s) read out of the document. They play in '
      + 'order across the span you set.'));

    var list = el('div', 'pseg-acts');
    for (var i = 0; i < parsed.acts.length; i += 1) {
      var a = el('div', 'pseg-act');
      a.appendChild(el('span', 'pseg-act-n', String(i + 1)));
      a.appendChild(el('span', 'pseg-act-t', parsed.acts[i]));
      list.appendChild(a);
    }
    node.appendChild(list);

    var hoursRow = el('div', 'pseg-hours');
    var lab = el('span', 'pseg-hours-l', 'Over');
    var val = el('span', 'pseg-hours-v', '7 hours');
    var slide = el('input', 'pseg-hours-s');
    slide.type = 'range';
    slide.min = '1';
    slide.max = '24';
    slide.step = '1';
    slide.value = '7';
    slide.setAttribute('aria-label', 'How many hours the plotline runs over');
    slide.addEventListener('input', function () {
      val.textContent = slide.value + (slide.value === '1' ? ' hour' : ' hours');
    });
    hoursRow.appendChild(lab);
    hoursRow.appendChild(slide);
    hoursRow.appendChild(val);
    node.appendChild(hoursRow);

    var go = el('button', 'pseg-go', 'Start it on the air');
    go.setAttribute('type', 'button');
    go.addEventListener('click', function () {
      go.disabled = true;
      go.textContent = 'writing it in...';
      var body = {
        title: String(name.value || parsed.title).slice(0, 120),
        acts: parsed.acts,
        span_minutes: Math.max(1, Math.min(2880, Number(slide.value) * 60)),
        loops: 0
      };
      send('POST', '/api/dj/plots', body).then(function (row) {
        if (!row || !row.id) {
          go.disabled = false; go.textContent = 'Start it on the air';
          note(node, 'the station would not take it');
          return;
        }
        /* Saved is not running: a plot has to be activated to reach the air,
           and a story he dropped in plainly wants to start. */
        send('POST', '/api/dj/plots/' + encodeURIComponent(row.id) + '/activate', {})
          .then(function () {
            go.textContent = 'on the air';
            note(node, 'running - act 1 begins at the next round it fits.');
          })['catch'](function () {
            note(node, 'saved, but it could not be started - start it from the plots desk');
          });
      })['catch'](function () {
        go.disabled = false; go.textContent = 'Start it on the air';
        note(node, 'could not reach the station');
      });
    });
    node.appendChild(go);

    root.document.body.appendChild(node);
    plotSheet = node;
    return node;
  }

  function shut() {
    if (plotSheet && plotSheet.parentNode) plotSheet.parentNode.removeChild(plotSheet);
    plotSheet = null;
    topicShut();
  }

  /* A document dropped anywhere on the given node becomes the window above.
     Only .md and .txt are taken; anything else is left alone so dropping a
     clip on the panel still does whatever it used to do. */
  function acceptDrops(node) {
    if (!node || node.__pinesegDrop) return;
    node.__pinesegDrop = true;
    node.addEventListener('dragover', function (ev) {
      if (!ev.dataTransfer) return;
      ev.preventDefault();
      try { ev.dataTransfer.dropEffect = 'copy'; } catch (err) { /* fine */ }
      node.classList.add('pseg-drop');
    });
    node.addEventListener('dragleave', function () { node.classList.remove('pseg-drop'); });
    node.addEventListener('drop', function (ev) {
      node.classList.remove('pseg-drop');
      if (!ev.dataTransfer || !ev.dataTransfer.files || !ev.dataTransfer.files.length) return;
      var file = ev.dataTransfer.files[0];
      if (!/\.(md|markdown|txt)$/i.test(file.name || '')) return;
      ev.preventDefault();
      var reader = new root.FileReader();
      reader.onload = function () {
        try { plotWindow(readMarkdown(String(reader.result || ''), file.name)); }
        catch (err) { /* a bad document never costs the panel */ }
      };
      try { reader.readAsText(file); } catch (err) { /* unreadable */ }
    });
  }

  root.PineSegments = {
    pane: pane,
    topics: topicsBlock,
    topicWindow: topicWindow,
    acceptDrops: acceptDrops,
    plotWindow: plotWindow,
    read: readMarkdown,
    close: shut
  };
})(typeof window !== 'undefined' ? window : globalThis);
