/* THE SFX DATABASE - THE SFX GUY'S CLIPS, AS A TABLE.
 *
 * "I want to be able to view the database and thumbnails of clips and review
 *  the information he is storing in a table where i can see clips, the tags,
 *  information and tables associated with an entry and edit, expand, review,
 *  delete and export."
 * "at the top put a search bar, I want to type anything and have it be looked
 *  up by the database showing suggestions in the window ... search for
 *  anything that is used as a tag in the database and search by clip name,
 *  folder, source, identified media tag, and any parameter that is used in
 *  the database."                                  - the operator, 2026-09-30
 *
 * THE ROADS (sfx_library.py):
 *   GET  /api/sfx/library?q=&sort=&limit=&offset=   the rows, with their tags
 *   GET  /api/sfx/library/suggest?q=                what the last word could be
 *   GET  /api/sfx/library/clip/<sid>                one entry, every field
 *   POST /api/sfx/library/clip/<sid>                seen / said / tags_add / tags_remove
 *   POST /api/sfx/library/export                    {q, sort, format} -> the recordings folder
 *   POST /api/sfx/ban, /api/sfx/weight, /api/sfx/delete   (the clip's own doors)
 *
 * THE BAR. Free words search the name, folder, source, path, what was said,
 * what the vision pass saw and the tags. A suggestion puts a `field:value`
 * token in the bar in place of the word being typed (tag:, folder:, source:,
 * name:, seen:, said:, id:, video:, seconds:, aired:, embedded:, tagged:, or a
 * facet). Arrow keys walk the suggestions, Enter takes one, Escape closes them.
 *
 * Opened from the file manager (its "SFX database" row) or PineSfxDb.open().
 */
(function (root) {
  'use strict';
  if (!root || !root.document || root.PineSfxDb) return;
  var document = root.document;
  var REQUEST_MS = 20000;
  var PAGE = 60;
  var FACETS = ['action', 'situation', 'emotional', 'intent', 'theme', 'metaphor', 'visual'];
  var ui = {pop: null, rows: [], total: 0, q: '', sort: 'name', seq: 0, sugSeq: 0, sug: [], sugAt: -1,
            open: {}, unwatch: null, unback: null, searchTimer: 0, sugTimer: 0, loading: false};

  /* ------------------------------------------------------------ roads */
  function bridge() { var b = root.pineDesktop; return b && typeof b.get === 'function' ? b : null; }
  function httpPage() { try { return /^https?:$/.test(String(root.location.protocol)); } catch (e) { return false; } }
  function stationUrl(u) {
    if (httpPage()) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (e) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }
  function stationKey() {
    try { if (typeof root.key === 'function') { var k = root.key(); if (typeof k === 'string' && k) return k; } } catch (e) { /* not the panel */ }
    try { /* eslint-disable-next-line no-undef */ if (typeof SERVER_KEY === 'string' && SERVER_KEY) return SERVER_KEY; } catch (e) { /* undeclared */ }
    try { return String(root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || ''); } catch (e) { return ''; }
  }
  function timeout(p, ms, what) {
    return new Promise(function (res, rej) {
      var done = false;
      var t = root.setTimeout(function () { if (!done) { done = true; rej(new Error(what + ' took too long')); } }, ms);
      Promise.resolve(p).then(function (v) { if (!done) { done = true; root.clearTimeout(t); res(v); } },
        function (e) { if (!done) { done = true; root.clearTimeout(t); rej(e); } });
    });
  }
  function request(method, path, body) {
    var b = bridge();
    var fn = b && (method === 'GET' ? b.get : b.post);
    if (fn) return timeout(fn.call(b, path, method === 'GET' ? undefined : (body || {})), REQUEST_MS, path);
    var headers = {};
    var key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    if (method !== 'GET') headers['Content-Type'] = 'application/json';
    return timeout(root.fetch(stationUrl(path), {method: method, headers: headers, cache: 'no-store',
      body: method === 'GET' ? undefined : JSON.stringify(body || {})}).then(function (res) {
      return res.text().then(function (text) {
        var data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (e) { data = {detail: text.slice(0, 200)}; }
        if (!res.ok) throw new Error(String((data && data.detail) || res.status));
        return data;
      });
    }), REQUEST_MS, path);
  }
  function get(p) { return request('GET', p); }
  function post(p, b) { return request('POST', p, b); }

  /* ------------------------------------------------------------ helpers */
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function ico(mark, fallback) {
    var s = make('span', 'sdb-ico');
    var m = '';
    try { m = typeof root.pineIcon === 'function' ? root.pineIcon(mark, '') : ''; } catch (e) { m = ''; }
    if (m) s.innerHTML = m; else s.textContent = fallback || '';
    return s;
  }
  function button(label, mark, fn, cls) {
    var b = make('button', 'sdb-btn' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    b.title = label;
    b.setAttribute('aria-label', label);
    if (mark) b.appendChild(ico(mark, ''));
    b.appendChild(make('span', '', label));
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(e); });
    return b;
  }
  function secs(s) { s = Number(s) || 0; return s >= 60 ? Math.floor(s / 60) + ':' + ('0' + Math.round(s % 60)).slice(-2) : s.toFixed(1) + ' s'; }
  function when(t) { try { return t ? new Date(Number(t) * 1000).toLocaleString() : '-'; } catch (e) { return '-'; } }
  function say(text, bad) { if (ui.status) { ui.status.textContent = text || ''; ui.status.classList.toggle('bad', !!bad); } }

  /* ------------------------------------------------------------ the window */
  function build() {
    if (ui.pop) return ui.pop;
    var pop = make('section', 'sdb-pop');
    pop.hidden = true;
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'SFX database');

    var head = make('div', 'sdb-head');
    head.appendChild(ico('c:archive', ''));
    var title = make('div', 'sdb-title');
    title.appendChild(make('b', '', 'SFX database'));
    ui.count = make('span', 'sdb-count', 'reading...');
    title.appendChild(ui.count);
    ui.vision = make('span', 'sdb-count sdb-vision', '');   /* [sfx-vision-idle] */
    title.appendChild(ui.vision);
    head.appendChild(title);
    pop.appendChild(head);

    /* the search bar, at the top */
    var bar = make('div', 'sdb-bar');
    var field = make('div', 'sdb-field');
    field.appendChild(ico('c:search', ''));
    ui.input = make('input', 'sdb-input');
    ui.input.type = 'search';
    ui.input.autocomplete = 'off';
    ui.input.spellcheck = false;
    ui.input.placeholder = 'Search anything: a tag, a name, a folder, a source, what he saw, what was said, video:yes, seconds:<5 ...';
    ui.input.setAttribute('aria-label', 'Search the SFX database');
    ui.input.setAttribute('aria-autocomplete', 'list');
    ui.input.addEventListener('input', onType);
    ui.input.addEventListener('keydown', onKey);
    ui.input.addEventListener('focus', function () { if (ui.sug.length) paintSuggest(); });
    field.appendChild(ui.input);
    var clear = make('button', 'sdb-clear');
    clear.type = 'button'; clear.title = 'Clear the search'; clear.setAttribute('aria-label', 'Clear the search');
    clear.appendChild(ico('c:close--filled', 'x'));
    clear.addEventListener('click', function () { ui.input.value = ''; hideSuggest(); runSearch(); ui.input.focus(); });
    field.appendChild(clear);
    ui.sugBox = make('div', 'sdb-sug');
    ui.sugBox.hidden = true;
    ui.sugBox.setAttribute('role', 'listbox');
    field.appendChild(ui.sugBox);
    bar.appendChild(field);
    ui.sortSel = make('select', 'sdb-sort');
    ui.sortSel.setAttribute('aria-label', 'Sort by');
    ui.sortSel.title = 'Sort by';
    [['name', 'Name'], ['folder', 'Folder'], ['seconds', 'Length'], ['aired', 'Most aired'],
     ['recent', 'Aired lately'], ['updated', 'Changed lately']].forEach(function (o) {
      var op = make('option', '', o[1]); op.value = o[0]; ui.sortSel.appendChild(op);
    });
    ui.sortSel.addEventListener('change', function () { ui.sort = ui.sortSel.value; runSearch(); });
    bar.appendChild(ui.sortSel);
    bar.appendChild(button('Export CSV', 'c:export', function () { exportRows('csv'); }));
    bar.appendChild(button('Export JSON', 'c:document', function () { exportRows('json'); }));
    pop.appendChild(bar);

    ui.status = make('div', 'sdb-status', '');
    pop.appendChild(ui.status);

    var wrap = make('div', 'sdb-tablewrap');
    var table = make('table', 'sdb-table');
    var thead = make('thead');
    var hr = make('tr');
    ['', 'Clip', 'Folder', 'Source', 'Length', 'Aired', 'Tags', 'Seen'].forEach(function (h) { hr.appendChild(make('th', '', h)); });
    thead.appendChild(hr);
    table.appendChild(thead);
    ui.body = make('tbody');
    table.appendChild(ui.body);
    wrap.appendChild(table);
    ui.more = button('Load more', 'c:chevron--down', function () { runSearch(true); }, 'sdb-more');
    ui.more.hidden = true;
    wrap.appendChild(ui.more);
    wrap.addEventListener('scroll', function () {
      if (!ui.more.hidden && !ui.loading && wrap.scrollTop + wrap.clientHeight > wrap.scrollHeight - 300) runSearch(true);
    });
    pop.appendChild(wrap);

    document.body.appendChild(pop);
    ui.pop = pop;
    if (typeof root.pineCloseX === 'function') {
      try { root.pineCloseX(pop, close, {label: 'Close the SFX database'}); } catch (e) { /* Escape still closes */ }
    }
    var dismiss = root.PineDismiss;
    if (dismiss && typeof dismiss.watch === 'function') {
      ui.unwatch = dismiss.watch(pop, close, [], function () { return !pop.hidden; });
    }
    if (dismiss && typeof dismiss.onBack === 'function') {
      ui.unback = dismiss.onBack(function () { return !pop.hidden ? {node: pop, close: close} : null; });
    }
    document.addEventListener('click', function (e) {
      if (ui.sugBox && !ui.sugBox.hidden && !field.contains(e.target)) hideSuggest();
    }, true);
    return pop;
  }

  function open(q) {
    build();
    ui.pop.hidden = false;
    if (typeof q === 'string') ui.input.value = q;
    runSearch();
    get('/api/sfx/vision/idle').then(function (v) {             /* [sfx-vision-idle] */
      ui.vision.textContent = 'He has studied ' + (Number(v.studied) || 0).toLocaleString() + ' of '
        + (Number(v.video) || 0).toLocaleString() + ' videos frame by frame - '
        + (v.now === 'studying' ? 'studying now' : 'he studies while the station is paused or off (now: ' + v.now + ')');
    }, function () { ui.vision.textContent = ''; });
    root.setTimeout(function () { try { ui.input.focus(); } catch (e) { /* tablet */ } }, 60);
  }
  function close() {
    if (!ui.pop) return;
    ui.pop.hidden = true;
    hideSuggest();
    ui.pop.querySelectorAll('video').forEach(function (v) { try { v.pause(); } catch (e) { /* gone */ } });
  }

  /* ------------------------------------------------------------ the bar */
  function lastToken(text) {
    /* the word being typed: from the last space that is not inside quotes */
    var inQ = false, at = 0;
    for (var i = 0; i < text.length; i += 1) {
      if (text[i] === '"') inQ = !inQ;
      else if (text[i] === ' ' && !inQ) at = i + 1;
    }
    return {start: at, word: text.slice(at)};
  }
  function onType() {
    root.clearTimeout(ui.sugTimer);
    root.clearTimeout(ui.searchTimer);
    ui.sugTimer = root.setTimeout(loadSuggest, 140);
    ui.searchTimer = root.setTimeout(function () { runSearch(); }, 380);
  }
  function loadSuggest() {
    var tok = lastToken(ui.input.value);
    var word = tok.word.trim();
    if (!word) { ui.sug = []; hideSuggest(); return; }
    var seq = ++ui.sugSeq;
    get('/api/sfx/library/suggest?q=' + encodeURIComponent(word)).then(function (got) {
      if (seq !== ui.sugSeq) return;
      ui.sug = (got && got.items) || [];
      ui.sugAt = -1;
      paintSuggest();
    }, function () { /* the search still runs */ });
  }
  var GROUP = {parameter: 'Search by', tag: 'Tags', folder: 'Folders', source: 'Sources', clip: 'Clips',
               seen: 'What he saw', said: 'What was said'};
  function paintSuggest() {
    var box = ui.sugBox;
    box.replaceChildren();
    if (!ui.sug.length) { box.hidden = true; return; }
    var last = '';
    ui.sug.forEach(function (s, i) {
      if (s.group !== last) { box.appendChild(make('div', 'sdb-sug-group', GROUP[s.group] || s.group)); last = s.group; }
      var item = make('div', 'sdb-sug-item' + (i === ui.sugAt ? ' on' : ''));
      item.setAttribute('role', 'option');
      item.appendChild(make('span', 'sdb-sug-label', s.label));
      if (s.detail) item.appendChild(make('span', 'sdb-sug-detail', s.detail));
      item.addEventListener('mousedown', function (e) { e.preventDefault(); take(i); });
      box.appendChild(item);
    });
    box.hidden = false;
  }
  function hideSuggest() { if (ui.sugBox) ui.sugBox.hidden = true; ui.sugAt = -1; }
  function take(i) {
    var s = ui.sug[i];
    if (!s) return;
    var text = ui.input.value;
    var tok = lastToken(text);
    var token = String(s.token || s.label);
    var parameterOnly = s.group === 'parameter' && /:$/.test(token);
    ui.input.value = text.slice(0, tok.start) + token + (parameterOnly ? '' : ' ');
    hideSuggest();
    ui.input.focus();
    if (parameterOnly) { loadSuggest(); return; }
    if (s.group === 'clip' && s.sid) ui.open[s.sid] = true;
    runSearch();
  }
  function onKey(e) {
    var open_ = ui.sugBox && !ui.sugBox.hidden && ui.sug.length;
    if (e.key === 'ArrowDown' && open_) { e.preventDefault(); ui.sugAt = (ui.sugAt + 1) % ui.sug.length; paintSuggest(); }
    else if (e.key === 'ArrowUp' && open_) { e.preventDefault(); ui.sugAt = (ui.sugAt - 1 + ui.sug.length) % ui.sug.length; paintSuggest(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (open_ && ui.sugAt >= 0) take(ui.sugAt);
      else { hideSuggest(); runSearch(); }
    } else if (e.key === 'Escape' && open_) { e.preventDefault(); e.stopPropagation(); hideSuggest(); }
  }

  /* ------------------------------------------------------------ the table */
  function runSearch(more) {
    var q = ui.input ? ui.input.value.trim() : '';
    var offset = more ? ui.rows.length : 0;
    var seq = ++ui.seq;
    ui.loading = true;
    if (!more) say('searching...');
    get('/api/sfx/library?q=' + encodeURIComponent(q) + '&sort=' + encodeURIComponent(ui.sort)
        + '&limit=' + PAGE + '&offset=' + offset).then(function (got) {
      if (seq !== ui.seq) return;
      ui.loading = false;
      ui.q = q;
      ui.total = Number(got.total) || 0;
      ui.rows = more ? ui.rows.concat(got.rows || []) : (got.rows || []);
      ui.count.textContent = ui.total.toLocaleString() + ' clip' + (ui.total === 1 ? '' : 's')
        + (q ? ' match' + (ui.total === 1 ? 'es' : '') + ' "' + q + '"' : ' in the database');
      say('');
      paintTable(more ? (got.rows || []) : null);
    }, function (err) {
      if (seq !== ui.seq) return;
      ui.loading = false;
      say('The database could not be read: ' + ((err && err.message) || err), true);
    });
  }
  function poster(r) {
    var cell = make('td', 'sdb-thumb');
    if (r.video && r.poster) {
      var img = make('img');
      img.loading = 'lazy';
      img.alt = '';
      img.src = stationUrl(r.poster);
      img.addEventListener('error', function () { cell.replaceChildren(ico('c:screen', 'V')); });
      cell.appendChild(img);
    } else {
      cell.appendChild(ico(r.video ? 'c:screen' : 'c:music', r.video ? 'V' : 'A'));
    }
    return cell;
  }
  function tagChips(tags, most) {
    var box = make('div', 'sdb-tags');
    (tags || []).slice(0, most || 99).forEach(function (t) {
      var c = make('span', 'sdb-tag' + (t.how === 'operator' ? ' mine' : ''), t.tag);
      c.title = t.facet + (t.how === 'operator' ? ' - your tag' : ' - ' + (t.how || 'tagged') + ', weight ' + t.weight);
      box.appendChild(c);
    });
    if (tags && most && tags.length > most) box.appendChild(make('span', 'sdb-tag more', '+' + (tags.length - most)));
    return box;
  }
  function rowNode(r) {
    var tr = make('tr', 'sdb-row' + (r.banned ? ' banned' : '') + (r.playable === false ? ' unplayable' : ''));
    tr.tabIndex = 0;
    tr.appendChild(poster(r));
    var nm = make('td', 'sdb-name');
    nm.appendChild(make('b', '', r.name || r.sid));
    nm.appendChild(make('span', 'sdb-id', '#' + r.sid + (r.banned ? '  -  banned' : '') + (r.playable === false ? '  -  not playable' : '')));
    tr.appendChild(nm);
    tr.appendChild(make('td', '', r.folder || '-'));
    tr.appendChild(make('td', '', r.source || '-'));
    tr.appendChild(make('td', 'sdb-num', secs(r.seconds)));
    tr.appendChild(make('td', 'sdb-num', String(r.aired || 0)));
    var tg = make('td');
    tg.appendChild(tagChips(r.tags, 6));
    tr.appendChild(tg);
    tr.appendChild(make('td', 'sdb-seen', r.seen || '-'));
    var toggle = function () { ui.open[r.sid] = !ui.open[r.sid]; paintDetail(r, tr); };
    tr.addEventListener('click', toggle);
    tr.addEventListener('keydown', function (e) { if (e.key === 'Enter') toggle(); });
    return tr;
  }
  function paintTable(appended) {
    if (!appended) ui.body.replaceChildren();
    (appended || ui.rows).forEach(function (r) {
      var tr = rowNode(r);
      ui.body.appendChild(tr);
      if (ui.open[r.sid]) paintDetail(r, tr);
    });
    if (!ui.rows.length) {
      var tr = make('tr');
      var td = make('td', 'sdb-empty', ui.q ? 'Nothing in the database matches that.' : 'The database is empty.');
      td.colSpan = 8;
      tr.appendChild(td);
      ui.body.appendChild(tr);
    }
    ui.more.hidden = ui.rows.length >= ui.total;
  }

  /* ------------------------------------------------------------ one entry */
  function paintDetail(r, tr) {
    var next = tr.nextSibling;
    if (next && next.classList && next.classList.contains('sdb-detail')) next.remove();
    tr.classList.toggle('open', !!ui.open[r.sid]);
    if (!ui.open[r.sid]) return;
    var dtr = make('tr', 'sdb-detail');
    var td = make('td');
    td.colSpan = 8;
    td.appendChild(make('div', 'sdb-dim', 'reading the entry...'));
    dtr.appendChild(td);
    tr.parentNode.insertBefore(dtr, tr.nextSibling);
    get('/api/sfx/library/clip/' + encodeURIComponent(r.sid)).then(function (c) {
      td.replaceChildren(detail(c, r, tr));
    }, function (err) {
      td.replaceChildren(make('div', 'sdb-dim bad', 'Could not read it: ' + ((err && err.message) || err)));
    });
  }
  function fact(dl, k, v) { dl.appendChild(make('dt', '', k)); dl.appendChild(make('dd', '', v == null || v === '' ? '-' : String(v))); }
  function detail(c, r, tr) {
    var box = make('div', 'sdb-entry');
    var left = make('div', 'sdb-media');
    var media = c.video ? make('video') : make('audio');
    media.controls = true;
    media.preload = 'none';
    media.src = stationUrl(c.media);
    if (c.video && c.poster) media.poster = stationUrl(c.poster);
    left.appendChild(media);
    var acts = make('div', 'sdb-acts');
    acts.appendChild(button(c.banned ? 'Unban' : 'Ban', 'c:misuse', function () {
      post('/api/sfx/ban', {id: c.sid, banned: !c.banned}).then(function (got) {
        r.banned = c.banned = !!got.banned; say(c.banned ? 'Banned: it will not air.' : 'Unbanned.');
        refreshRow(r, tr);
      }, function (e) { say('Could not change the ban: ' + e.message, true); });
    }));
    var del = button('Delete', 'c:trash-can', function () {
      if (!del.classList.contains('armed')) {
        del.classList.add('armed'); del.lastChild.textContent = 'Tap again to delete';
        root.setTimeout(function () { del.classList.remove('armed'); del.lastChild.textContent = 'Delete'; }, 4000);
        return;
      }
      post('/api/sfx/delete', {id: c.sid}).then(function (got) {
        say((got && got.say) || 'Deleted.');
        ui.open[c.sid] = false;
        runSearch();
      }, function (e) { say('Could not delete it: ' + e.message, true); });
    }, 'danger');
    acts.appendChild(del);
    acts.appendChild(button('Export entry', 'c:export', function () {
      post('/api/sfx/library/export', {q: 'id:' + c.sid, format: 'json'}).then(function (got) {
        say(got.say || 'Exported.');
      }, function (e) { say('Could not export it: ' + e.message, true); });
    }));
    var wrow = make('label', 'sdb-weight');
    wrow.appendChild(make('span', '', 'How often he reaches for it'));
    var w = make('input'); w.type = 'range'; w.min = '0'; w.max = '3'; w.step = '0.1'; w.value = String(c.weight == null ? 1 : c.weight);
    var wv = make('output', '', Number(w.value).toFixed(1) + 'x');
    w.addEventListener('input', function () { wv.textContent = Number(w.value).toFixed(1) + 'x'; });
    w.addEventListener('change', function () {
      post('/api/sfx/weight', {id: c.sid, weight: Number(w.value)}).then(function () { say('Weight saved.'); },
        function (e) { say('Could not save the weight: ' + e.message, true); });
    });
    wrow.appendChild(w); wrow.appendChild(wv);
    acts.appendChild(wrow);
    left.appendChild(acts);
    box.appendChild(left);

    var right = make('div', 'sdb-info');
    var dl = make('dl', 'sdb-facts');
    fact(dl, 'Name', c.name); fact(dl, 'Id', c.sid); fact(dl, 'Folder', c.folder); fact(dl, 'Source', c.source);
    fact(dl, 'Path', c.path); fact(dl, 'Kind', c.video ? 'video' : 'sound'); fact(dl, 'Length', secs(c.seconds));
    fact(dl, 'Aired', (c.aired || 0) + ' time' + (c.aired === 1 ? '' : 's') + (c.last_aired ? ', last ' + when(c.last_aired) : ''));
    fact(dl, 'Playable', c.playable === false ? 'no' : c.playable ? 'yes' : '-');
    fact(dl, 'Size', c.bytes ? (c.bytes / 1048576).toFixed(1) + ' MB' : '-');
    fact(dl, 'Embedded', c.embedded ? 'yes' : 'not yet'); fact(dl, 'Tagged', c.tagged ? 'yes' : 'not yet');
    fact(dl, 'Seen at', when(c.seen_at)); fact(dl, 'Heard at', when(c.said_at));
    right.appendChild(dl);

    right.appendChild(make('h4', '', 'Tags'));
    var tags = make('div', 'sdb-tags edit');
    (c.tags || []).forEach(function (t) {
      var chip = make('span', 'sdb-tag' + (t.how === 'operator' ? ' mine' : ''));
      chip.appendChild(make('i', '', t.facet));
      chip.appendChild(make('span', '', t.tag));
      chip.title = t.how === 'operator' ? 'your tag' : (t.how || 'tagged') + ', weight ' + t.weight;
      var x = make('button', 'sdb-tag-x');
      x.type = 'button'; x.title = 'Remove this tag'; x.setAttribute('aria-label', 'Remove the tag ' + t.tag);
      x.textContent = 'x';
      x.addEventListener('click', function (e) {
        e.stopPropagation();
        post('/api/sfx/library/clip/' + c.sid, {tags_remove: [{facet: t.facet, tag: t.tag}]}).then(function () {
          chip.remove(); r.tags = (r.tags || []).filter(function (o) { return !(o.facet === t.facet && o.tag === t.tag); });
          refreshRow(r, tr); say('Tag removed.');
        }, function (err) { say('Could not remove it: ' + err.message, true); });
      });
      chip.appendChild(x);
      tags.appendChild(chip);
    });
    right.appendChild(tags);
    var add = make('div', 'sdb-addtag');
    var facet = make('select');
    facet.setAttribute('aria-label', 'Facet for the new tag');
    FACETS.forEach(function (f) { var o = make('option', '', f); o.value = f; facet.appendChild(o); });
    facet.value = 'visual';
    var tagIn = make('input');
    tagIn.type = 'text'; tagIn.placeholder = 'add a tag'; tagIn.setAttribute('aria-label', 'New tag');
    var addIt = function () {
      var v = tagIn.value.trim();
      if (!v) return;
      post('/api/sfx/library/clip/' + c.sid, {tags_add: [{facet: facet.value, tag: v}]}).then(function () {
        r.tags = (r.tags || []).concat([{facet: facet.value, tag: v, how: 'operator', weight: 1}]);
        refreshRow(r, tr); paintDetail(r, tr); say('Tag added - it is yours: the keeper will not take it away.');
      }, function (err) { say('Could not add it: ' + err.message, true); });
    };
    tagIn.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addIt(); } });
    add.appendChild(facet); add.appendChild(tagIn); add.appendChild(button('Add', 'c:add', addIt));
    right.appendChild(add);

    var edits = [['seen', 'What he saw in it (the vision pass, comma-separated)', c.seen],
                 ['said', 'What is said in it (the transcript)', c.said]];
    edits.forEach(function (e) {
      right.appendChild(make('h4', '', e[1]));
      var ta = make('textarea', 'sdb-text');
      ta.value = e[2] || '';
      ta.rows = e[0] === 'said' ? 3 : 2;
      right.appendChild(ta);
      var save = button('Save', 'c:save', function () {
        var body = {}; body[e[0]] = ta.value;
        post('/api/sfx/library/clip/' + c.sid, body).then(function () {
          if (e[0] === 'seen') r.seen = ta.value; else r.said = ta.value;
          refreshRow(r, tr); say('Saved - the matcher is rebuilt and the keeper re-embeds it.');
        }, function (err) { say('Could not save it: ' + err.message, true); });
      });
      right.appendChild(save);
    });
    if (c.frames && c.frames.length) {
      right.appendChild(make('h4', '', 'Frames he looked at'));
      var fl = make('div', 'sdb-frames');
      c.frames.forEach(function (f) {
        var row = make('div', 'sdb-frame');
        row.appendChild(make('b', '', secs(f.at)));
        row.appendChild(make('span', '', f.desc || '-'));
        fl.appendChild(row);
      });
      right.appendChild(fl);
    }
    if (c.dialogue && c.dialogue.length) {
      right.appendChild(make('h4', '', 'His lines about it'));
      var ul = make('ul', 'sdb-lines');
      c.dialogue.forEach(function (d) { ul.appendChild(make('li', '', (d.who ? d.who + ': ' : '') + d.text)); });
      right.appendChild(ul);
    }
    box.appendChild(right);
    return box;
  }
  function refreshRow(r, tr) {
    /* the cells change in place: the open entry under it keeps its row */
    var fresh = rowNode(r);
    tr.className = fresh.className;
    tr.classList.toggle('open', !!ui.open[r.sid]);
    tr.replaceChildren.apply(tr, Array.prototype.slice.call(fresh.childNodes));
    return tr;
  }

  /* ------------------------------------------------------------ export */
  function exportRows(fmt) {
    say('exporting...');
    post('/api/sfx/library/export', {q: ui.input.value.trim(), sort: ui.sort, format: fmt}).then(function (got) {
      say(got.say || 'Exported.');
    }, function (e) { say('Could not export: ' + e.message, true); });
  }

  root.PineSfxDb = {open: open, close: close, search: function (q) { open(q); }};
})(typeof window !== 'undefined' ? window : globalThis);
