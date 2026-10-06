/* [llm-command] LLM COMMAND - the book of every command the assistant understands, counted.
 *
 * "when it comes to LLM commands, I want a popup where I am mapping them and
 * their behavior and am able to view them on a table and adjust them. Call the
 * popup 'LLM command' and I want to be able to add commands that then are able
 * to be expanded on and used with the Nabu / Pine box. List every command we
 * have assigned so far and keep a count of how many times I use commands
 * through the LLM assistant."                          - the operator, 2026-10-06
 *
 * Reads GET /api/llm-commands (llm_commands.py): every built-in parser of
 * generate_answer, every verb of the orchestrator's command line, and the
 * operator's own commands, each with what it does, its example sentences or
 * triggers, how many times it has answered and when it last did. Notes are
 * edited in place, built-ins can be switched off, custom commands are added,
 * edited and removed, and "Try a sentence" asks the station which command
 * would answer it (a dry run - nothing is counted).
 *
 * One file for the desk, the PiP tools page and the tablet: the request goes
 * through the preload bridge where there is one, else fetch with the page's
 * key (the same split supercut-review.js carries). The reader is never moved:
 * a repaint keeps the scroll where it was, a focused notes box is never
 * rewritten under the thumb, and nothing here scrolls anything into view.
 *
 *   PineLlmCommands.open()          the popup, with its X
 *   PineLlmCommands.close()
 *   PineLlmCommands.mount(host)     the book inside any element (the tablet's view)
 */
(function (root) {
  'use strict';
  if (root.PineLlmCommands) return;
  var doc = root.document;
  var POLL_MS = 8000;
  var KINDS = {builtin: 'built-in', orchestrator: 'orchestrator', custom: 'custom'};
  var SORTS = [
    ['chain', 'chain order', function (r) { return (r.kind === 'builtin' ? 0 : r.kind === 'orchestrator' ? 1 : 2) * 1000 + (Number(r.order) || 0); }],
    ['name', 'name', function (r) { return String(r.name || '').toLowerCase(); }],
    ['count', 'count', function (r) { return -(Number(r.count) || 0); }],
    ['last', 'last used', function (r) { return -(Number(r.last_at) || 0); }]
  ];

  function make(tag, cls, text) {
    var node = doc.createElement(tag); if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text); return node;
  }
  function request(method, path, body) {
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge[method.toLowerCase()] === 'function') return Promise.resolve(bridge[method.toLowerCase()](path, body));
    var headers = {}, key = root.PINE_KEY || root.__PINE_VIDEO_EDITOR_KEY || '';
    if (key) headers.Authorization = 'Bearer ' + key;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    var base = root.PINE_BASE || (/^https?:/.test(root.location.protocol) ? '' : 'http://10.89.1.246:8096');
    return root.fetch(base + path, {method: method, headers: headers, cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (got) { if (!r.ok) throw new Error(typeof got.detail === 'string' ? got.detail : got.why || 'The station refused this action.'); return got; }); });
  }
  function get(path) { return request('GET', path); }
  function post(path, body) { return request('POST', path, body || {}); }

  function when(ts) {
    if (!ts) return '-';
    var d = new Date(Number(ts) * 1000);
    var p = function (x) { return (x < 10 ? '0' : '') + x; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function ago(ts) {
    if (!ts) return 'never';
    var s = Math.max(0, Date.now() / 1000 - Number(ts));
    if (s < 90) return Math.round(s) + ' s ago';
    if (s < 5400) return Math.round(s / 60) + ' min ago';
    if (s < 172800) return (s / 3600).toFixed(1) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }
  function cut(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n - 3).replace(/\s+\S*$/, '') + '...' : s; }
  function button(host, label, title, action, cls) {
    var b = make('button', cls || 'lc-btn', label); b.type = 'button'; b.title = title || label;
    b.addEventListener('click', function () { action(b); }); host.appendChild(b); return b;
  }
  function field(host, label, kind, rows) {
    var lab = make('label', 'lc-field'), title = make('span', '', label), input = make(kind || 'input');
    input.setAttribute('aria-label', label); if (rows) input.rows = rows; lab.appendChild(title); lab.appendChild(input); host.appendChild(lab); return input;
  }

  function mount(host, opts) {
    opts = opts || {};
    var state = {rows: [], sig: '', sort: 'chain', dir: 1, q: '', kind: '', timer: 0, busy: false, editing: '', dead: false, say: ''};
    try { var saved = JSON.parse(root.localStorage.getItem('pine.llmcommands') || '{}'); if (saved.sort) state.sort = saved.sort; if (saved.dir) state.dir = saved.dir; } catch (e) { /* first run */ }
    host.textContent = '';
    host.classList.add('lc-host');

    var head = make('div', 'lc-head');
    head.appendChild(make('b', 'lc-title', 'LLM command'));
    var status = make('span', 'lc-status', 'reading the book...'); status.setAttribute('role', 'status');
    head.appendChild(status);
    host.appendChild(head);
    host.appendChild(make('p', 'lc-intro', 'Every sentence the Nabu or the panel hands the assistant is offered to these commands first, in chain order; the first to answer owns the turn and the chat model only gets what none of them wants. Counts are one per sentence.'));

    var bar = make('div', 'lc-bar');
    var search = make('input', 'lc-search'); search.type = 'search'; search.placeholder = 'filter: name, words, example...'; search.setAttribute('aria-label', 'Filter the commands');
    search.addEventListener('input', function () { state.q = String(search.value || '').toLowerCase(); paint(true); });
    bar.appendChild(search);
    var kindSel = make('select', 'lc-kind'); kindSel.setAttribute('aria-label', 'Which commands to show'); kindSel.title = 'Which commands to show';
    [['', 'all commands'], ['builtin', 'built-in'], ['orchestrator', 'orchestrator verbs'], ['custom', 'my commands']].forEach(function (k) { var o = make('option', '', k[1]); o.value = k[0]; kindSel.appendChild(o); });
    kindSel.addEventListener('change', function () { state.kind = kindSel.value; paint(true); });
    bar.appendChild(kindSel);
    bar.appendChild(make('span', 'lc-label', 'sort by'));
    var sortBtns = {};
    SORTS.forEach(function (s) {
      sortBtns[s[0]] = button(bar, s[1], 'Sort by ' + s[1] + ' (press again to reverse)', function () {
        if (state.sort === s[0]) state.dir = -state.dir; else { state.sort = s[0]; state.dir = 1; }
        remember(); paint(true);
      }, 'lc-sort');
    });
    button(bar, 'Refresh', 'Read the book again now', function () { load(true); });
    host.appendChild(bar);

    /* Try a sentence: which command would answer it (dry run, nothing counted) */
    var tryBox = make('div', 'lc-try');
    var tryIn = make('input', 'lc-try-in'); tryIn.type = 'text'; tryIn.placeholder = 'Try a sentence: which command would answer it?'; tryIn.setAttribute('aria-label', 'A sentence to try');
    tryBox.appendChild(tryIn);
    var tryOut = make('div', 'lc-try-out', ''); tryOut.setAttribute('role', 'status');
    function tryIt() {
      var text = String(tryIn.value || '').trim();
      if (!text) { tryOut.textContent = 'Type a sentence first.'; return; }
      tryOut.textContent = 'asking...';
      post('/api/llm-commands/try', {text: text}).then(function (got) {
        if (state.dead) return;
        tryOut.textContent = '';
        tryOut.appendChild(make('b', '', got.say || ''));
        if (got.rewritten) tryOut.appendChild(make('div', 'lc-try-line', 'said to the parsers as: "' + got.rewritten + '"'));
        if (got.orchestrator) tryOut.appendChild(make('div', 'lc-try-line', 'orchestrator line: ' + got.orchestrator));
        if (got.also && got.also.length) tryOut.appendChild(make('div', 'lc-try-line', 'matched, in chain order: ' + got.also.join(', ')));
        if (got.skipped && got.skipped.length) tryOut.appendChild(make('div', 'lc-try-line', 'switched off: ' + got.skipped.join(', ')));
        var id = (got.custom && got.custom.id) || got.builtin;
        Array.prototype.forEach.call(tbody.children, function (tr) { tr.classList.toggle('lc-hit', !!id && tr.dataset.id === id); });
      }).catch(function (e) { if (!state.dead) tryOut.textContent = 'The station did not answer: ' + (e && e.message || e); });
    }
    button(tryBox, 'Try', 'Ask the station which command would answer this sentence (nothing is counted)', tryIt);
    tryIn.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); tryIt(); } });
    host.appendChild(tryBox);
    host.appendChild(tryOut);

    /* the table */
    var wrap = make('div', 'lc-wrap');
    var table = make('table', 'lc-table');
    var thead = make('thead'), hr = make('tr');
    ['Name', 'What it does', 'Examples / triggers', 'Count', 'Last used', 'Enabled'].forEach(function (h) { hr.appendChild(make('th', '', h)); });
    thead.appendChild(hr); table.appendChild(thead);
    var tbody = make('tbody'); table.appendChild(tbody);
    wrap.appendChild(table);
    host.appendChild(wrap);

    /* add / edit a command */
    var add = make('details', 'lc-add');
    var addSum = make('summary', '', 'Add command'); add.appendChild(addSum);
    var form = make('div', 'lc-form'); add.appendChild(form);
    form.appendChild(make('p', 'lc-help', 'A trigger is a whole sentence as you would say it to the Nabu ("hey pine box" and "please" are ignored; * stands for anything), or /a regex/. What it does: say it to the station AS another sentence the built-in commands understand, answer with a fixed reply, or run a line of the orchestrator\'s command line (more banter, run repair, drive:banter ...).'));
    var fName = field(form, 'Name', 'input'); fName.placeholder = 'e.g. Cut me a tape';
    var fTriggers = field(form, 'Triggers, one per line', 'textarea', 3); fTriggers.placeholder = 'cut me a tape\ntape that\n/^save (that|this) bit$/';
    var fKind = field(form, 'What it does', 'select');
    [['as', 'say it to the station as ...'], ['say', 'answer with a fixed reply ...'], ['orchestrator', 'run the orchestrator line ...']].forEach(function (k) { var o = make('option', '', k[1]); o.value = k[0]; fKind.appendChild(o); });
    var fText = field(form, 'The sentence, reply or line', 'input'); fText.placeholder = 'export the last five minutes';
    var fNotes = field(form, 'Notes', 'textarea', 2); fNotes.placeholder = 'why this command exists, what it is for';
    var formBar = make('div', 'lc-form-bar'); form.appendChild(formBar);
    var formSay = make('span', 'lc-form-say', ''); formSay.setAttribute('role', 'status');
    function resetForm() { state.editing = ''; fName.value = ''; fTriggers.value = ''; fKind.value = 'as'; fText.value = ''; fNotes.value = ''; addSum.textContent = 'Add command'; cancelBtn.hidden = true; }
    var saveBtn = button(formBar, 'Save command', 'Save this command to the book', function (b) {
      var body = {name: fName.value, triggers: String(fTriggers.value || '').split(/\r?\n/), does: {}, notes: fNotes.value};
      body.does[fKind.value] = fText.value;
      if (state.editing) body.id = state.editing;
      b.disabled = true; formSay.textContent = 'saving...';
      post('/api/llm-commands/custom', body).then(function (got) {
        if (state.dead) return; formSay.textContent = got.say || 'saved.'; resetForm(); load(true);
      }).catch(function (e) { if (!state.dead) formSay.textContent = 'Not saved: ' + (e && e.message || e); }).then(function () { if (!state.dead) b.disabled = false; });
    });
    var cancelBtn = button(formBar, 'Cancel edit', 'Stop editing and clear the form', function () { resetForm(); formSay.textContent = ''; });
    cancelBtn.hidden = true;
    formBar.appendChild(formSay);
    host.appendChild(add);
    saveBtn.classList.add('lc-primary');

    function remember() { try { root.localStorage.setItem('pine.llmcommands', JSON.stringify({sort: state.sort, dir: state.dir})); } catch (e) { /* no storage */ } }

    function load(force) {
      if (state.busy || state.dead) return;
      state.busy = true;
      (typeof opts.get === 'function' ? Promise.resolve(opts.get('/api/llm-commands')) : get('/api/llm-commands')).then(function (got) {
        state.busy = false;
        if (state.dead) return;
        if (!got || !Array.isArray(got.rows)) { status.textContent = 'the book could not be read'; return; }
        state.say = got.say || '';
        status.textContent = state.say;
        var sig = got.rows.map(function (r) { return r.id + ':' + r.count + ':' + r.last_at + ':' + r.enabled + ':' + (r.notes || '').length + ':' + (r.examples || []).join('|') + ':' + (r.text || ''); }).join('\n');
        if (sig === state.sig && !force) return;
        state.rows = got.rows;
        state.sig = sig;
        paint(false);
      }).catch(function (e) { state.busy = false; if (!state.dead) status.textContent = 'the book could not be read: ' + (e && e.message || e); });
    }

    function visible() {
      var q = state.q;
      var rows = state.rows.filter(function (r) {
        if (state.kind && r.kind !== state.kind) return false;
        if (!q) return true;
        var hay = [r.id, r.name, r.does, r.verb, r.notes, r.text, (r.examples || []).join(' '), r.last_text, KINDS[r.kind]].join(' ').toLowerCase();
        return hay.indexOf(q) >= 0;
      });
      var spec = SORTS.filter(function (s) { return s[0] === state.sort; })[0] || SORTS[0];
      var keyOf = spec[2];
      rows.sort(function (a, b) {
        var ka = keyOf(a), kb = keyOf(b);
        var c = (ka < kb ? -1 : ka > kb ? 1 : 0);
        if (c === 0) c = SORTS[0][2](a) - SORTS[0][2](b);
        return c * state.dir;
      });
      return rows;
    }

    function saveNote(r, area, say) {
      var text = String(area.value || '');
      if (text === String(r.notes || '')) return;
      say.textContent = 'saving note...';
      post('/api/llm-commands/note/' + encodeURIComponent(r.id), {notes: text}).then(function () {
        if (state.dead) return; r.notes = text; say.textContent = 'noted ' + when(Date.now() / 1000);
      }).catch(function (e) { if (!state.dead) say.textContent = 'note not saved: ' + (e && e.message || e); });
    }

    function row(r) {
      var tr = make('tr', 'lc-row lc-' + r.kind);
      tr.dataset.id = r.id;
      var tdName = make('td', 'lc-name'); tdName.dataset.label = 'Name';
      tdName.appendChild(make('b', '', r.name || r.id));
      var meta = KINDS[r.kind] + (r.kind === 'builtin' ? ' - chain #' + r.order : '') + (r.verified === 'runtime' ? ' - reads station state' : '');
      tdName.appendChild(make('div', 'lc-meta', meta));
      tdName.appendChild(make('div', 'lc-id', r.kind === 'custom' ? r.id : (r.kind === 'orchestrator' ? r.verb : r.id + '()')));
      if (r.present === false) tdName.appendChild(make('div', 'lc-warn', 'not found on the station'));
      if (r.kind === 'custom') {
        var acts = make('div', 'lc-acts');
        button(acts, 'Edit', 'Put this command into the form below to change it', function () {
          state.editing = r.id; fName.value = r.name || ''; fTriggers.value = (r.triggers || []).join('\n'); fKind.value = r.how || 'as'; fText.value = r.text || ''; fNotes.value = r.notes || '';
          addSum.textContent = 'Edit command: ' + r.name; add.open = true; cancelBtn.hidden = false; formSay.textContent = '';
        }, 'lc-btn lc-small');
        button(acts, 'Delete', 'Remove this command from the book', function (b) {
          if (b.dataset.armed !== '1') { b.dataset.armed = '1'; b.textContent = 'Delete, really?'; root.setTimeout(function () { b.dataset.armed = ''; b.textContent = 'Delete'; }, 4000); return; }
          post('/api/llm-commands/custom/' + encodeURIComponent(r.id) + '/delete', {}).then(function () { if (!state.dead) load(true); })
            .catch(function (e) { if (!state.dead) status.textContent = 'not removed: ' + (e && e.message || e); });
        }, 'lc-btn lc-small lc-danger');
        tdName.appendChild(acts);
      }
      tr.appendChild(tdName);

      var tdDoes = make('td', 'lc-does'); tdDoes.dataset.label = 'What it does';
      tdDoes.appendChild(make('div', 'lc-does-text', r.does || ''));
      if (r.returns) tdDoes.appendChild(make('div', 'lc-returns', 'returns: ' + r.returns));
      if (r.depends) tdDoes.appendChild(make('div', 'lc-returns', 'depends on: ' + r.depends));
      var notes = make('textarea', 'lc-notes'); notes.rows = 1; notes.placeholder = 'notes...'; notes.value = r.notes || ''; notes.setAttribute('aria-label', 'Notes on ' + (r.name || r.id));
      var noteSay = make('div', 'lc-note-say', '');
      notes.addEventListener('blur', function () { saveNote(r, notes, noteSay); });
      notes.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); notes.blur(); } });
      tdDoes.appendChild(notes); tdDoes.appendChild(noteSay);
      tr.appendChild(tdDoes);

      var tdEx = make('td', 'lc-ex'); tdEx.dataset.label = r.kind === 'custom' ? 'Triggers' : 'Examples';
      var ul = make('ul', 'lc-list');
      (r.examples || []).forEach(function (ex) { ul.appendChild(make('li', '', ex)); });
      tdEx.appendChild(ul);
      if (r.kind === 'custom') tdEx.appendChild(make('div', 'lc-custom-does', (r.how === 'as' ? 'as: ' : r.how === 'say' ? 'says: ' : 'orchestrator: ') + (r.text || '')));
      tr.appendChild(tdEx);

      var tdCount = make('td', 'lc-count', String(Number(r.count) || 0)); tdCount.dataset.label = 'Count';
      tr.appendChild(tdCount);
      var tdLast = make('td', 'lc-last'); tdLast.dataset.label = 'Last used';
      fillLast(tdLast, r);
      tr.appendChild(tdLast);

      var tdOn = make('td', 'lc-on'); tdOn.dataset.label = 'Enabled';
      var sw = make('input'); sw.type = 'checkbox'; sw.checked = r.enabled !== false;
      sw.setAttribute('aria-label', (r.enabled !== false ? 'Switch off ' : 'Switch on ') + (r.name || r.id));
      sw.title = r.kind === 'orchestrator' ? 'The orchestrator verbs are always on; they are typed, not overheard' : (r.kind === 'builtin' ? 'Off: this parser answers nothing and the chain moves on' : 'Off: these triggers are ignored');
      if (r.kind === 'orchestrator') sw.disabled = true;
      sw.addEventListener('change', function () {
        post('/api/llm-commands/note/' + encodeURIComponent(r.id), {enabled: sw.checked}).then(function () { if (!state.dead) load(true); })
          .catch(function (e) { if (!state.dead) { sw.checked = !sw.checked; status.textContent = 'not changed: ' + (e && e.message || e); } });
      });
      tdOn.appendChild(sw);
      tr.appendChild(tdOn);
      return tr;
    }

    function fillLast(td, r) {
      td.textContent = '';
      td.appendChild(make('div', 'lc-ago', ago(r.last_at)));
      if (r.last_at) { var w = make('div', 'lc-when', when(r.last_at)); td.appendChild(w); }
      if (r.last_text) { var t = make('div', 'lc-last-text', '"' + cut(r.last_text, 90) + '"'); t.title = r.last_text; td.appendChild(t); }
    }

    function paint(keepScroll) {
      var top = wrap.scrollTop;
      Object.keys(sortBtns).forEach(function (k) {
        sortBtns[k].classList.toggle('on', k === state.sort);
        sortBtns[k].textContent = (SORTS.filter(function (s) { return s[0] === k; })[0] || [])[1] + (k === state.sort ? (state.dir > 0 ? ' (asc)' : ' (desc)') : '');
      });
      var rows = visible();
      var order = rows.map(function (r) { return r.id; }).join('|');
      var have = Array.prototype.map.call(tbody.children, function (tr) { return tr.dataset.id; }).join('|');
      var focused = doc.activeElement && tbody.contains(doc.activeElement);
      if (order !== have || !keepScroll && !focused) {
        if (focused && order === have) return;        /* never rewrite the row under the thumb */
        var frag = doc.createDocumentFragment();
        if (!rows.length) { var e = make('tr', 'lc-empty'); var td = make('td', '', state.rows.length ? 'nothing matches the filter' : 'the book is empty'); td.colSpan = 6; e.appendChild(td); frag.appendChild(e); }
        rows.forEach(function (r) { frag.appendChild(row(r)); });
        tbody.textContent = '';
        tbody.appendChild(frag);
      } else {
        /* same rows: refresh the live cells in place, leave the notes alone */
        var byId = {};
        rows.forEach(function (r) { byId[r.id] = r; });
        Array.prototype.forEach.call(tbody.children, function (tr) {
          var r = byId[tr.dataset.id]; if (!r) return;
          var c = tr.querySelector('.lc-count'); if (c) c.textContent = String(Number(r.count) || 0);
          var l = tr.querySelector('.lc-last'); if (l) fillLast(l, r);
          var sw = tr.querySelector('.lc-on input'); if (sw && sw !== doc.activeElement) sw.checked = r.enabled !== false;
        });
      }
      wrap.scrollTop = top;
    }

    load(true);
    state.timer = root.setInterval(function () {
      if (!host.isConnected || state.dead) { root.clearInterval(state.timer); return; }
      if (host.offsetParent === null && !opts.always) return;   /* hidden: do not fetch */
      load(false);
    }, Number(opts.pollMs) || POLL_MS);
    return {
      refresh: function () { load(true); },
      close: function () { state.dead = true; root.clearInterval(state.timer); },
      count: function () { return state.rows.length; }
    };
  }

  /* the popup */
  var ui = {back: null, box: null, api: null};
  function build() {
    if (ui.back) return ui.back;
    var back = make('div', 'lc-back'); back.id = 'pineLlmCommands';
    var box = make('div', 'lc-box'); box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'LLM command');
    var bar = make('div', 'lc-topbar');
    bar.appendChild(make('b', '', 'LLM command'));
    var x = make('button', 'lc-x', 'X'); x.type = 'button'; x.title = 'Close the LLM command book'; x.setAttribute('aria-label', 'Close the LLM command book');
    x.addEventListener('click', close);
    bar.appendChild(x);
    if (typeof root.pineCloseX === 'function') { root.pineCloseX(box, close, {label: 'Close the LLM command book'}); x.style.display = 'none'; }   /* [closex:llm-command] */
    box.appendChild(bar);
    var body = make('div', 'lc-body');
    box.appendChild(body);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) close(); });
    doc.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && back.classList.contains('show') && typeof root.pineCloseX !== 'function') close(); });
    doc.body.appendChild(back);
    ui.back = back; ui.box = box; ui.body = body;
    return back;
  }
  function open() {
    build();
    ui.back.classList.add('show');
    if (ui.api) ui.api.close();
    ui.api = mount(ui.body, {always: true});
  }
  function close() {
    if (ui.api) { ui.api.close(); ui.api = null; }
    if (ui.back) ui.back.classList.remove('show');
  }
  function isOpen() { return !!(ui.back && ui.back.classList.contains('show')); }

  root.PineLlmCommands = {open: open, close: close, mount: mount, isOpen: isOpen, SORTS: SORTS.map(function (s) { return s[0]; })};
})(typeof window !== 'undefined' ? window : this);
