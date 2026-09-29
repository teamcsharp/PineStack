#!/usr/bin/env python3
"""[outlandish] The desk and kiosk views (apply to BOTH copies, they stay identical):

  console-line.js  [outl-audit]      the AUDIT bar gains an OUTLANDISH button (the lines at or
                                     above the audit threshold in the last 6 h) opening the review
                                     list: filters (hours, score, tag), CSV/JSON export, and a tap
                                     opens the line's popup; an OUTLANDISH row on the marquee or in
                                     the audit terminal opens its line too
  line-actions.js  [outl-react-mark] a clip's hold menu: "Mark as a reaction" + the categories
  script-page.js   [outl-fam]        the roll tiles' colours for MEASURE / SFXREACT / CUTIN /
                                     MINIROUND / HOLD

usage: outlandish_views_patch.py --check|--apply <file>.js   (0 ready, 2 applied, 1 missing)
       the file's basename picks its edits (desktop/renderer/X.js and
       app/src/main/assets/pine-views/X.js)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

AUDIT_JS = r"""  /* [outl-audit] THE OUTLANDISH REVIEW. The meter (outlandish.py) scores every
     aired line 0-100 and never filters it; a line at or above the audit
     threshold lands on the AUDIT line (station flow node "outlandish") and
     here: #code, seat, words, score, tags, whether a dispute followed (aired /
     planned but cut / none) and the SFX Guy's reaction. Filters, CSV/JSON
     export for the scientists, and a tap opens the line's popup. Polls
     /api/outlandish every 30 s. */
  var OUTL_POLL_MS = 30000;
  var outl = {count: 0, items: [], got: null, timer: null, busy: false, hours: 6, min: -1, tag: ''};

  function outlStyle() {
    if (typeof document === 'undefined' || document.getElementById('pineOutlStyle')) return;
    var s = document.createElement('style');
    s.id = 'pineOutlStyle';
    s.textContent = '.pine-console-outl{display:inline-flex;align-items:center;gap:3px;color:#ff6b8b;'
      + 'background:none;border:0;padding:0 6px;cursor:pointer;font:600 11px/1 system-ui,sans-serif}'
      + '.pine-console-outl svg{width:14px;height:14px}'
      + '#pineOutlList .pine-outl-ctl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 10px}'
      + '#pineOutlList .pine-outl-ctl select,#pineOutlList .pine-outl-ctl input{font:inherit;max-width:9em}'
      + '#pineOutlList .pine-outl-ctl button{font:inherit;cursor:pointer}'
      + '#pineOutlList .pine-outl-sum{padding:4px 10px;opacity:.85;font-size:12px}'
      + '#pineOutlList .pine-outl-row{display:block;width:100%;text-align:left;padding:6px 10px;border:0;'
      + 'border-top:1px solid rgba(127,127,127,.25);background:none;color:inherit;font:inherit;cursor:pointer}'
      + '#pineOutlList .pine-outl-row b{display:inline-block;min-width:2.2em;color:#ff6b8b;margin-right:6px}'
      + '#pineOutlList .pine-outl-row i{opacity:.75;font-style:normal;margin-left:6px}'
      + '#pineOutlList .pine-outl-row span{display:block;opacity:.9;font-size:12px;margin-top:2px}';
    (document.head || document.body).appendChild(s);
  }

  function outlButton(bar) {
    bar = bar || el();
    if (!bar || !bar.querySelector) return null;
    var b = bar.querySelector('.pine-console-outl');
    if (b) return b;
    outlStyle();
    b = document.createElement('button');
    b.type = 'button';
    b.className = 'pine-console-outl';
    b.innerHTML = (icon('c:scales', 'OUTLANDISH review') || 'O') + '<span class="pine-console-outl-n"></span>';
    b.addEventListener('click', function (event) {
      event.stopPropagation();
      event.preventDefault();
      outlOpen(bar);
    });
    bar.insertBefore(b, bar.querySelector('.pine-console-gallery') || bar.firstChild);
    outlPaint();
    return b;
  }

  function outlPaint() {
    var b = outlButton();
    if (!b) return;
    var n = b.querySelector('.pine-console-outl-n');
    if (n) n.textContent = outl.count > 99 ? '99+' : String(outl.count || 0);
    var t = 'OUTLANDISH: ' + outl.count + ' aired line' + (outl.count === 1 ? '' : 's')
      + ' at or above the audit threshold in the last 6 h - open the review (measured, never filtered)';
    if (b.title !== t) { b.title = t; b.setAttribute('aria-label', t); }
  }

  function outlPath(hours, full) {
    return '/api/outlandish?hours=' + encodeURIComponent(String(hours)) + '&limit=' + (full ? '1000' : '80')
      + '&follow=' + (full ? '1' : '0') + (outl.min >= 0 && full ? '&min=' + encodeURIComponent(String(outl.min)) : '');
  }

  function outlPoll() {
    if (outl.busy) return Promise.resolve();
    outl.busy = true;
    var done = function () { outl.busy = false; };
    return flowGet(outlPath(6, false)).then(function (got) {
      outl.count = Number(got && got.count) || 0;
      outlPaint();
    }).then(done, done);
  }

  function outlOpenRow(row) {
    var f = row && row._flow;
    var d = f && f.details;
    if (!f || f.node !== 'outlandish' || !d || !d.line_id) return false;
    return outlOpenLine({line_id: d.line_id, text: d.text, who: d.who});
  }

  function outlOpenLine(it) {
    var line = {id: String(it.line_id || ''), said: String(it.text || ''), who: String(it.who || '')};
    if (!line.id) return false;
    try {
      if (root.PineLineActions && typeof root.PineLineActions.open === 'function') { root.PineLineActions.open(line); return true; }
    } catch (err) { /* the trace below */ }
    return false;
  }

  function outlFollowWord(f) {
    return f === 'aired' ? 'dispute aired' : f === 'planned_cut' ? 'dispute planned, cut' : f === 'none' ? 'no dispute' : '';
  }

  function outlCsv(items) {
    var q = function (v) { v = String(v == null ? '' : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var out = ['code,aired_utc,who,road,score,level,tags,cues,follow,reaction,text,line_id,conversation_id,turn_id'];
    items.forEach(function (r) {
      var rx = r.reaction || {};
      out.push([r.code, new Date(Number(r.at) * 1000).toISOString(), r.who, r.road, r.score, r.level,
        (r.tags || []).join('|'), (r.cues || []).map(function (c) { return c.label + ': ' + c.match; }).join('|'),
        r.follow || '', rx.label || '', r.text, r.line_id, r.conversation_id || '', r.turn_id || ''].map(q).join(','));
    });
    return out.join('\n') + '\n';
  }

  function outlSave(name, text, type) {
    try {
      var url = URL.createObjectURL(new Blob([text], {type: type}));
      var a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    } catch (err) { /* nothing to save into here */ }
  }

  function outlRender(list) {
    var body = list.querySelector('.pine-console-list-body');
    var count = list.querySelector('.pine-console-list-count');
    var got = outl.got || {};
    var th = got.thresholds || {};
    var items = (got.items || []).filter(function (r) { return !outl.tag || (r.tags || []).indexOf(outl.tag) >= 0; });
    if (count) count.textContent = items.length + ' in ' + outl.hours + ' h';
    if (!body) return;
    body.textContent = '';
    var ctl = document.createElement('div');
    ctl.className = 'pine-outl-ctl';
    var hours = document.createElement('select');
    hours.setAttribute('aria-label', 'hours');
    [1, 6, 24, 72].forEach(function (h) {
      var o = document.createElement('option');
      o.value = String(h); o.textContent = 'last ' + h + ' h'; o.selected = h === outl.hours;
      hours.appendChild(o);
    });
    hours.addEventListener('change', function () { outl.hours = Number(hours.value) || 6; outlLoad(list); });
    var min = document.createElement('input');
    min.type = 'number'; min.min = '0'; min.max = '100'; min.step = '5';
    min.value = String(outl.min >= 0 ? outl.min : (got.floor != null ? got.floor : ''));
    min.title = 'the lowest score listed (the audit threshold is ' + (th.audit != null ? th.audit : '?') + ')';
    min.setAttribute('aria-label', min.title);
    min.addEventListener('change', function () { outl.min = Math.max(0, Math.min(100, Number(min.value) || 0)); outlLoad(list); });
    var tag = document.createElement('select');
    tag.setAttribute('aria-label', 'tag');
    var any = document.createElement('option');
    any.value = ''; any.textContent = 'every tag';
    tag.appendChild(any);
    Object.keys(got.by_tag || {}).forEach(function (k) {
      var o = document.createElement('option');
      o.value = k; o.textContent = k + ' (' + got.by_tag[k] + ')'; o.selected = k === outl.tag;
      tag.appendChild(o);
    });
    tag.addEventListener('change', function () { outl.tag = tag.value; outlRender(list); });
    var csv = document.createElement('button');
    csv.type = 'button'; csv.textContent = 'CSV'; csv.title = 'Export the list as CSV';
    csv.addEventListener('click', function (e) { e.stopPropagation(); outlSave('outlandish-' + outl.hours + 'h.csv', outlCsv(items), 'text/csv'); });
    var js = document.createElement('button');
    js.type = 'button'; js.textContent = 'JSON'; js.title = 'Export the list and its summary as JSON';
    js.addEventListener('click', function (e) { e.stopPropagation(); outlSave('outlandish-' + outl.hours + 'h.json', JSON.stringify(got, null, 1), 'application/json'); });
    [hours, min, tag, csv, js].forEach(function (x) { ctl.appendChild(x); });
    body.appendChild(ctl);
    var f = got.follow || {};
    var cost = got.cost || {};
    body.appendChild(untracedLine(items.length + ' of ' + (got.lines || 0) + ' measured lines at or above '
      + (got.floor != null ? got.floor : '?') + ' - dispute aired ' + (f.aired || 0) + ', planned but cut '
      + (f.planned_cut || 0) + ', none ' + (f.none || 0) + ' - thresholds audit ' + (th.audit != null ? th.audit : '?')
      + ' / react ' + (th.react != null ? th.react : '?') + ' / dispute ' + (th.dispute != null ? th.dispute : '?')
      + ' - the meter costs ' + (cost.rule_us_per_line != null ? cost.rule_us_per_line : '?') + ' us a line. Measured, never filtered.',
      'pine-outl-sum'));
    var dist = got.distribution || {};
    body.appendChild(untracedLine('scores: ' + Object.keys(dist).map(function (k) { return k + ' ' + dist[k]; }).join(' | '), 'pine-outl-sum'));
    items.forEach(function (it) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'pine-outl-row';
      var b = document.createElement('b');
      b.textContent = String(it.score);
      row.appendChild(b);
      var when = '';
      try { when = new Date(Number(it.at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
      catch (err) { when = ''; }
      row.appendChild(document.createTextNode((it.code || '') + ' ' + (it.who || '') + ' ' + when));
      var meta = document.createElement('i');
      var rx = it.reaction || {};
      meta.textContent = [(it.tags || []).join(', '), outlFollowWord(it.follow), rx.label ? 'SFX: ' + rx.label : '']
        .filter(Boolean).join(' - ');
      row.appendChild(meta);
      var words = document.createElement('span');
      words.textContent = String(it.text || '').slice(0, 220);
      row.appendChild(words);
      row.title = (it.cues || []).map(function (c) { return c.label + ': "' + c.match + '"'; }).join('; ')
        + (it.follow_why ? ' - ' + it.follow_why : '');
      row.addEventListener('click', function (event) {
        event.stopPropagation();
        outlOpenLine(it);
      });
      body.appendChild(row);
    });
  }

  function outlLoad(list) {
    return flowGet(outlPath(outl.hours, true)).then(function (got) {
      outl.got = got || {};
      if (outl.hours === 6) { outl.count = Number(got && got.count) || 0; outlPaint(); }
      if (list.isConnected) outlRender(list);
    }, function (err) {
      var body = list.querySelector('.pine-console-list-body');
      if (body) body.textContent = 'The OUTLANDISH review is not available: ' + String((err && err.message) || err);
    });
  }

  function outlOpen(bar) {
    if (typeof document === 'undefined') return;
    var old = document.getElementById('pineOutlList');
    if (old) { old.remove(); return; }
    outlStyle();
    var list = document.createElement('div');
    list.id = 'pineOutlList';
    list.className = 'pine-console-list';
    list.setAttribute('role', 'dialog');
    list.setAttribute('aria-label', 'OUTLANDISH review');
    list.setAttribute('data-pine-drag', '');
    list.innerHTML = '<div class="pine-console-list-head" data-pine-drag-handle>'
      + '<b>OUTLANDISH review</b><span class="pine-console-list-count"></span>'
      + '<button type="button" class="pine-console-list-close" aria-label="Close" title="Close">x</button>'
      + '</div><div class="pine-console-list-body">reading the meter...</div>';
    list.querySelector('.pine-console-list-close').addEventListener('click', function (event) {
      event.stopPropagation();
      list.remove();
    });
    document.body.appendChild(list);
    outlLoad(list);
    if (root.PineDismiss) root.PineDismiss.watch(list, function () { list.remove(); }, [bar || el()]);
  }

  function outlStart() {
    if (typeof document === 'undefined') return;
    outlButton();
    outlPoll();
    if (!outl.timer) {
      outl.timer = root.setInterval(function () { outlButton(); outlPoll(); }, OUTL_POLL_MS);
      if (outl.timer && typeof outl.timer.unref === 'function') outl.timer.unref();
    }
  }

"""

REACT_JS = r"""  /* [outl-react-mark] "Mark as a reaction": files this clip in the SFX Guy's
   * reaction repertoire under one of his SFXREACT1 topics. A thumbs-up on
   * top of a mark makes it the strongest candidate he has for that reaction;
   * a thumbs-down weighs it down. The station says what it filed under the
   * header, like a vote. */
  var REACTIONS = [['gasp', 'Gasp'], ['boo', 'Boo'], ['record_scratch', 'Record scratch'], ['what', 'What?!'],
    ['uproar', 'Uproar'], ['sad_trombone', 'Sad trombone'], ['cringe', 'Cringe'], ['laugh', 'Laugh'],
    ['fail', 'Fail'], ['victory', 'Victory'], ['rimshot', 'Rimshot'], ['crickets', 'Crickets']];
  function reactionStyle() {
    if (typeof document === 'undefined' || document.getElementById('laReactStyle')) return;
    var s = document.createElement('style');
    s.id = 'laReactStyle';
    s.textContent = '.la-react{padding:6px 10px}.la-react-head{display:block;font-size:12px;opacity:.8;margin-bottom:4px}'
      + '.la-react-row{display:flex;flex-wrap:wrap;gap:4px}.la-react-chip{font:inherit;font-size:12px;padding:3px 8px;'
      + 'border-radius:12px;border:1px solid rgba(127,127,127,.45);background:none;color:inherit;cursor:pointer}'
      + '.la-react-chip.on{background:#ffd479;color:#222;border-color:#ffd479}';
    (document.head || document.body).appendChild(s);
  }
  function reactionChips(line) {
    reactionStyle();
    var box = make('div', 'la-react');
    box.appendChild(make('b', 'la-react-head', 'Mark as a reaction (the SFX Guy files it)'));
    var row = make('div', 'la-react-row');
    REACTIONS.forEach(function (r) {
      var b = make('button', 'la-react-chip', r[1]);
      b.type = 'button';
      b.title = 'File this clip as a "' + r[1] + '" reaction in the SFX Guy\'s repertoire';
      b.setAttribute('aria-label', b.title);
      press(b, function () {
        Promise.resolve().then(function () {
          return api().post('/api/sfxguy/reactions/mark', {line_id: line.id, category: r[0]});
        }).then(function (got) {
          if (got && got.ok === false) throw new Error(String(got.why || 'the station would not take that'));
          [].slice.call(row.children).forEach(function (x) { x.classList.toggle('on', x === b); });
          voteSay('Filed as a ' + r[1] + ' reaction' + (got && got.up ? ' - with your upvote, one of his strongest' : ''), false);
        }).catch(function (err) { voteSay(String((err && err.message) || err || 'the station would not take that'), true); });
      });
      row.appendChild(b);
    });
    box.appendChild(row);
    return box;
  }

"""

EDITS_BY_FILE = {
    "console-line.js": [
        ("[outl-audit]", "before", "  function start() {\n", AUDIT_JS),
        ("[outl-audit-start]", "after",
         "    untracedStart();                                   /* [s3-account] */\n",
         "    outlStart();                                       /* [outl-audit-start] */\n"),
        ("[outl-audit-marquee]", "replace",
         "      if (entry && entry.__row) {\n"
         "        if (root.PineConsoleTrace) root.PineConsoleTrace.open(entry.__row);\n",
         "      if (entry && entry.__row) {\n"
         "        if (outlOpenRow(entry.__row)) return;          /* [outl-audit-marquee] an OUTLANDISH row opens its line */\n"
         "        if (root.PineConsoleTrace) root.PineConsoleTrace.open(entry.__row);\n"),
        ("[outl-audit-terminal]", "replace",
         "        list.remove();\n"
         "        if (root.PineConsoleTrace) root.PineConsoleTrace.open(row);\n",
         "        list.remove();\n"
         "        if (outlOpenRow(row)) return;                  /* [outl-audit-terminal] */\n"
         "        if (root.PineConsoleTrace) root.PineConsoleTrace.open(row);\n"),
        ("[outl-audit-api]", "replace",
         "    untraced: function () { return untracedOpen(el()); }};   /* [s3-account] */\n",
         "    untraced: function () { return untracedOpen(el()); },   /* [s3-account] */\n"
         "    outlandish: function () { return outlOpen(el()); }};   /* [outl-audit-api] */\n"),
    ],
    "line-actions.js": [
        ("[outl-react-mark]", "before", "  function open(line) {\n", REACT_JS),
        ("[outl-react-chips]", "before",
         "    if (sfxRow && !sfxRow.deleted) {\n"
         "      choice(list, 'c:edit', 'Edit and split this sound effect',\n",
         "    if (sfxRow && !sfxRow.deleted && line.id) list.appendChild(reactionChips(line));   /* [outl-react-chips] */\n"),
    ],
    "script-page.js": [
        ("[outl-fam]", "replace",
         "    MEMORY: '#d9c9a3', STATION: '#9aa9ab', GRAPH: '#9be15d'};\n",
         "    MEMORY: '#d9c9a3', STATION: '#9aa9ab', GRAPH: '#9be15d',\n"
         "    MEASURE: '#ff6b8b', SFXREACT: '#ffd479', CUTIN: '#c4a1ee', MINIROUND: '#87bfff', HOLD: '#d9c9a3'};   /* [outl-fam] */\n"),
    ],
}

if __name__ == "__main__":
    if len(sys.argv) < 3 or os.path.basename(sys.argv[2]) not in EDITS_BY_FILE:
        print(__doc__)
        sys.exit(1)
    sys.exit(run(EDITS_BY_FILE[os.path.basename(sys.argv[2])], sys.argv))
