"""[s3-account] The three surfaces of the origin ledger, marker-idempotent:

  frontend/system3.js            every item's card (feed dice, script line, Message
                                 view, messenger - all open mountLineStory) ends in
                                 its ORIGIN CHAIN from /api/system3/origin/<id>: the
                                 verdict (rolled / forced / rogue), the air receipt,
                                 the script place, the System 3 conversation, every
                                 roll, the store, the forced reason or rogue path -
                                 including the lines System 3 did not direct
  desktop/renderer/script-page.js  (+ the kiosk copy) the Message view's store badge
                                 reads the origin ledger for a line of any age
                                 (/api/screenplay/<hour>/line/<id>?origin=1, asked last)
  desktop/renderer/console-line.js (+ the kiosk copy) the base bar's UNTRACED ALARM:
                                 a Carbon warning--alt button before the gallery, shown
                                 while anything aired in 24 h with no System 3 origin;
                                 it opens the Untraced list (the code paths, each item's
                                 origin chain on tap, the 24 h coverage by road)

python3 tools/edit_s3_origin_views.py --check | --apply  [repo root]
--check exits 0 ready / 2 applied / 1 anchors missing. The desktop and kiosk
copies must be identical before the edit and stay identical; each keeps its own
line ending (LF stays LF, CRLF stays CRLF); a mixed file is refused.
"""
import sys
from pathlib import Path

SYSTEM3 = ("frontend/system3.js",)
SCRIPT_PAGE = ("desktop/renderer/script-page.js", "app/src/main/assets/pine-views/script-page.js")
CONSOLE = ("desktop/renderer/console-line.js", "app/src/main/assets/pine-views/console-line.js")

ORIGIN_JS = r"""/* [s3-account] THE ORIGIN LEDGER ON EVERY ITEM. "trace its origin for each and
   every thing down to either a table that is accessed via a roulette option or
   whatever system is needing to encompass the rogue element" (the operator).
   /api/system3/origin/<id> answers for any aired item of any age: rolled (the
   tables and the dice), forced (the named road and its trigger - no dice), or
   rogue (the code path that aired it, on the Untraced list). */
const ORIGIN_WORD = {rolled: 'Rolled by System 3', forced: 'A forced node', rogue: 'Rogue - aired with no System 3 origin'};
const ORIGIN_TONE = {rolled: 'var(--s3-good, #2e7d4f)', forced: 'var(--s3-warn, #8a6d1a)', rogue: 'var(--s3-bad, #b3261e)'};
function originLabel(n) {
  return ({air: 'On air', script: 'In the script', road: 'The road', conversation: 'System 3',
    roll: n.scope === 'round' ? 'A round roll' : 'A roll', store: 'Drawn from', forced: 'Forced by',
    rogue: 'Aired by'})[n.node] || String(n.node || '');
}
function originText(n) {
  const bits = [];
  const add = (v, pre) => { if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length)) bits.push((pre || '') + (Array.isArray(v) ? v.join(' - ') : String(v))); };
  if (n.node === 'air') {
    add(n.at ? new Date(Number(n.at) * 1000).toLocaleString([], {weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '');
    add(n.aired, 'published: '); add(n.heard_at ? 'heard' : ''); add(n.seconds ? Number(n.seconds).toFixed(1) + ' s' : '');
  } else if (n.node === 'script') {
    add(n.block != null ? 'block ' + n.block + (n.ord != null ? '.' + n.ord : '') : ''); add(n.sid, 'round '); add(n.segment, 'segment ');
  } else if (n.node === 'road') {
    add(n.label); add(n.who, 'seat ');
  } else if (n.node === 'conversation') {
    add(n.conversation_id, 'conversation '); add(n.turn_id, 'turn '); add(n.road, 'road '); add(n.via);
  } else if (n.node === 'roll') {
    add(n.table); add(n.path); add(n.picked || n.label);
    add(n.dice != null ? 'd100 ' + n.dice : ''); add(n.index != null && n.of ? n.index + ' of ' + n.of : '');
    add(n.odds != null ? 'odds ' + Math.round(Number(n.odds) * 100) + '%' : '');
  } else if (n.node === 'store') {
    add(n.kind); add(n.folder, 'folder '); add(n.db, 'db '); add(n.pool, 'pool '); add(n.product);
    add(n.key, 'key '); add(n.file, 'file '); add(n.index != null && n.of ? n.index + ' of ' + n.of : '');
  } else if (n.node === 'forced') {
    add(n.road); add(n.trigger); add(n.detail); add(n.by, 'by '); add(n.how);
  } else if (n.node === 'rogue') {
    add(n.producer); add(n.why); add(n.path, 'path ');
  }
  return bits.join(' - ');
}
function originNodes(got) {
  const v = String((got && got.verdict) || '');
  const head = el('div', {class: 's3-origin-head s3-origin-' + v, style: 'margin:4px 0 6px;color:' + (ORIGIN_TONE[v] || 'inherit')},
    el('b', {text: ORIGIN_WORD[v] || v || 'Unknown'}), (got && got.why) ? ' - ' + got.why : '');
  const mk = n => el('div', {class: 's3-origin-node s3-origin-' + String(n.node || ''),
    style: 'padding:2px 0 2px 10px;border-left:2px solid ' + (n.node === 'rogue' ? ORIGIN_TONE.rogue : n.node === 'forced' ? ORIGIN_TONE.forced : 'rgba(127,127,127,.35)')},
    el('b', {text: originLabel(n) + ': '}), originText(n));
  const all = (got && got.nodes) || [];
  const round = all.filter(n => n.node === 'roll' && n.scope === 'round');
  const rows = all.filter(n => !(n.node === 'roll' && n.scope === 'round')).map(mk);
  /* the conversation's own rolls (the station's dice door, the round's shape) are
     many and shared by every line of the round: folded, never hidden */
  const folded = round.length ? el('details', {class: 's3-origin-round'},
    el('summary', {text: round.length + ' roll' + (round.length === 1 ? '' : 's') + ' on the round (its conversation)'}),
    ...round.map(mk)) : null;
  const kept = (got && got.retention) ? para('Kept: ' + got.retention + (got.settled === false ? ' - still settling' : ''), 's3-muted') : null;
  return [head, ...rows, folded, kept];
}
function originSection(request, lineId) {
  const box = el('div', 's3-origin', para('Reading the origin ledger...', 's3-muted'));
  if (!lineId) { fill(box, para('No line id - nothing to trace.', 's3-muted')); return box; }
  Promise.resolve().then(() => request('/api/system3/origin/' + encodeURIComponent(lineId))).then(
    got => fill(box, ...originNodes(got)),
    () => fill(box, para('The origin ledger holds no record of this line yet - it writes each item within a minute or two of the air.', 's3-muted')));
  return box;
}
export function mountOrigin(root, {request, lineId = ''} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3');
  fill(root, originSection(request, lineId));
  return {dispose() { fill(root); }};
}

export async function mountLineStory("""

SYSTEM3_EDITS = [
    ("origin-section",
     "export async function mountLineStory(",
     ORIGIN_JS),
    ("origin-on-guy",
     "    fill(root, sfxGuyStory(conv, got.sfxguy, v));\n",
     "    fill(root, sfxGuyStory(conv, got.sfxguy, v),\n"
     "      sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */\n"),
    ("origin-on-part",
     "    tell(false, 'in a System 3 round, but not one of its turns');\n",
     "    root.append(sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */\n"
     "    tell(false, 'in a System 3 round, but not one of its turns');\n"),
    ("origin-on-undirected",
     "    tell(false, 'not directed by System 3');\n",
     "    root.append(sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */\n"
     "    tell(false, 'not directed by System 3');\n"),
    ("origin-on-directed",
     "    sectionOf('The checks on this turn', verdict));\n",
     "    sectionOf('The checks on this turn', verdict),\n"
     "    sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */\n"),
]

SCRIPT_PAGE_EDITS = [
    ("prov-any-age",
     "    return ask(hourKey).then(function (p) {\n"
     "      var back = mvHourBefore(hourKey);\n"
     "      return p || !back ? p : ask(back);\n"
     "    });\n",
     "    return ask(hourKey).then(function (p) {\n"
     "      var back = mvHourBefore(hourKey);\n"
     "      return p || !back ? p : ask(back);\n"
     "    }).then(function (p) {\n"
     "      /* [s3-account] a line older than the hour tree: the origin ledger answers */\n"
     "      return p || ask(hourKey, 1);\n"
     "    });\n"),
    ("prov-ask-origin",
     "    var ask = function (key) {\n"
     "      return Promise.resolve().then(function () {\n"
     "        return api().get('/api/screenplay/' + encodeURIComponent(key) + '/line/' + encodeURIComponent(lid));\n",
     "    var ask = function (key, origin) {\n"
     "      return Promise.resolve().then(function () {\n"
     "        return api().get('/api/screenplay/' + encodeURIComponent(key) + '/line/' + encodeURIComponent(lid)\n"
     "          + (origin ? '?origin=1' : ''));   /* [s3-account] */\n"),
    ("stores-from-ledger",
     "      if (prov.air && prov.air.replay) put('reair', 're-aired: a line already heard, played again');\n",
     "      if (prov.air && prov.air.replay) put('reair', 're-aired: a line already heard, played again');\n"
     "      /* [s3-account] the origin ledger names the store for a line of any age */\n"
     "      ((prov.origin && prov.origin.nodes) || []).forEach(function (n) {\n"
     "        if (!n || n.node !== 'store' || !n.kind) return;\n"
     "        put('ledger:' + String(n.kind), 'the ' + String(n.kind)\n"
     "          + (n.folder ? ' - ' + String(n.folder) : '') + (n.db ? ' - ' + String(n.db) : '')\n"
     "          + (n.product ? ' - ' + String(n.product) : '') + (n.key ? ' (' + String(n.key).slice(0, 40) + ')' : ''));\n"
     "      });\n"),
]

CONSOLE_JS = r"""  /* [s3-account] THE UNTRACED ALARM. An item that airs with no System 3 origin
     airs (the air is never held) and lands on the Untraced list; this button
     before the gallery shows while the list is not empty (24 h) and opens it:
     the code paths that aired them, each item's origin chain on tap, and the
     24 h coverage by road. Polls /api/system3/untraced every 30 s. */
  var UNTRACED_POLL_MS = 30000;
  var untraced = {count: 0, total: 0, items: [], by: [], timer: null, busy: false};

  function untracedStyle() {
    if (typeof document === 'undefined' || document.getElementById('pineUntracedStyle')) return;
    var s = document.createElement('style');
    s.id = 'pineUntracedStyle';
    s.textContent = '.pine-console-untraced{display:inline-flex;align-items:center;gap:3px;color:#e8a33d;'
      + 'background:none;border:0;padding:0 6px;cursor:pointer;font:600 11px/1 system-ui,sans-serif}'
      + '.pine-console-untraced[hidden]{display:none}.pine-console-untraced svg{width:14px;height:14px}'
      + '#pineUntracedList .pine-untraced-sum{padding:6px 10px;opacity:.85}'
      + '#pineUntracedList .pine-untraced-row{display:block;width:100%;text-align:left;padding:6px 10px;'
      + 'border:0;border-top:1px solid rgba(127,127,127,.25);background:none;color:inherit;font:inherit;cursor:pointer}'
      + '#pineUntracedList .pine-untraced-row b{margin-right:6px}'
      + '#pineUntracedList .pine-untraced-chain{padding:4px 10px 8px 22px;font-size:12px;opacity:.9}'
      + '#pineUntracedList .pine-untraced-chain div{padding:1px 0}';
    (document.head || document.body).appendChild(s);
  }

  function untracedButton(bar) {
    bar = bar || el();
    if (!bar || !bar.querySelector) return null;
    var b = bar.querySelector('.pine-console-untraced');
    if (b) return b;
    untracedStyle();
    b = document.createElement('button');
    b.type = 'button';
    b.className = 'pine-console-untraced';
    b.hidden = true;
    b.innerHTML = (icon('c:warning--alt', 'Untraced air') || '!') + '<span class="pine-console-untraced-n"></span>';
    b.addEventListener('click', function (event) {
      event.stopPropagation();
      event.preventDefault();
      untracedOpen(bar);
    });
    bar.insertBefore(b, bar.querySelector('.pine-console-gallery') || bar.firstChild);
    untracedPaint();
    return b;
  }

  function untracedPaint() {
    var b = untracedButton();
    if (!b) return;
    b.hidden = !(untraced.count > 0);
    var n = b.querySelector('.pine-console-untraced-n');
    if (n) n.textContent = untraced.count > 99 ? '99+' : String(untraced.count || '');
    var t = untraced.count + ' item' + (untraced.count === 1 ? '' : 's')
      + ' aired in the last 24 h with no System 3 origin - open the Untraced list';
    if (b.title !== t) { b.title = t; b.setAttribute('aria-label', t); }
  }

  function untracedPoll() {
    if (untraced.busy) return Promise.resolve();
    untraced.busy = true;
    var done = function () { untraced.busy = false; };
    return flowGet('/api/system3/untraced?hours=24&limit=60').then(function (got) {
      got = got || {};
      untraced.count = Number(got.count) || 0;
      untraced.total = Number(got.items_total) || 0;
      untraced.items = got.items || [];
      untraced.by = got.by_path || [];
      untracedPaint();
      var list = document.getElementById('pineUntracedList');
      if (list) untracedRender(list);
    }).then(done, done);
  }

  function untracedLine(text, cls) {
    var d = document.createElement('div');
    if (cls) d.className = cls;
    d.textContent = text;
    return d;
  }

  function untracedChainText(n) {
    var keys = {air: ['aired', 'seconds'], script: ['block', 'ord', 'sid'], road: ['label', 'who'],
      conversation: ['conversation_id', 'turn_id'], roll: ['table', 'picked', 'dice', 'of'],
      store: ['kind', 'folder', 'db', 'pool', 'product', 'key', 'file'],
      forced: ['road', 'trigger', 'by'], rogue: ['producer', 'why', 'path']}[n.node] || [];
    var out = [];
    keys.forEach(function (k) { if (n[k] !== undefined && n[k] !== null && n[k] !== '') out.push(String(n[k])); });
    return (n.node || '') + ': ' + out.join(' - ');
  }

  function untracedRender(list) {
    var body = list.querySelector('.pine-console-list-body');
    var count = list.querySelector('.pine-console-list-count');
    if (count) count.textContent = untraced.count + ' of ' + untraced.total + ' in 24 h';
    if (!body) return;
    body.textContent = '';
    var sum = untracedLine(untraced.count
      ? 'These aired with no System 3 origin. Each is a road to bring under System 3.'
      : 'Nothing untraced in the last 24 hours: every item traced to a roll or a named forced node.',
      'pine-untraced-sum');
    body.appendChild(sum);
    untraced.by.slice(0, 6).forEach(function (p) {
      body.appendChild(untracedLine(p.count + ' x ' + (p.producer || 'unknown') + ' (' + (p.road || '') + ')', 'pine-untraced-sum'));
    });
    var cov = untracedLine('coverage: reading...', 'pine-untraced-sum');
    body.appendChild(cov);
    flowGet('/api/system3/coverage?hours=24').then(function (rep) {
      var t = (rep && rep.totals) || {};
      cov.textContent = 'coverage 24 h: ' + (t.traced_pct == null ? '-' : t.traced_pct + '%') + ' traced - '
        + (t.rolled || 0) + ' rolled, ' + (t.forced || 0) + ' forced, ' + (t.rogue || 0) + ' rogue of '
        + (t.items || 0) + ' items. The daily report: /system3-coverage';
    }, function () { cov.textContent = 'coverage: not available'; });
    untraced.items.forEach(function (it) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'pine-untraced-row';
      var when = '';
      try { when = new Date(Number(it.air_at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
      catch (err) { when = ''; }
      var b = document.createElement('b');
      b.textContent = when + ' ' + (it.road || '');
      row.appendChild(b);
      row.appendChild(document.createTextNode((it.producer || 'unknown') + ' - ' + String(it.text || '').slice(0, 120)));
      row.addEventListener('click', function (event) {
        event.stopPropagation();
        var open = row.nextSibling && row.nextSibling.className === 'pine-untraced-chain' ? row.nextSibling : null;
        if (open) { open.remove(); return; }
        var chain = document.createElement('div');
        chain.className = 'pine-untraced-chain';
        chain.textContent = 'reading the origin ledger...';
        body.insertBefore(chain, row.nextSibling);
        flowGet('/api/system3/origin/' + encodeURIComponent(it.line_id)).then(function (got) {
          chain.textContent = '';
          chain.appendChild(untracedLine((got && got.verdict || '') + ' - ' + (got && got.why || '')));
          var rounds = 0;
          ((got && got.nodes) || []).forEach(function (n) {
            if (n.node === 'roll' && n.scope === 'round') { rounds += 1; return; }
            chain.appendChild(untracedLine(untracedChainText(n)));
          });
          if (rounds) chain.appendChild(untracedLine(rounds + ' roll(s) on the round - open the line in System 3 for them'));
        }, function () { chain.textContent = 'no origin record for ' + it.line_id; });
      });
      body.appendChild(row);
    });
  }

  function untracedOpen(bar) {
    if (typeof document === 'undefined') return;
    var old = document.getElementById('pineUntracedList');
    if (old) { old.remove(); return; }
    var list = document.createElement('div');
    list.id = 'pineUntracedList';
    list.className = 'pine-console-list';
    list.setAttribute('role', 'dialog');
    list.setAttribute('aria-label', 'Untraced air');
    list.setAttribute('data-pine-drag', '');
    list.innerHTML = '<div class="pine-console-list-head" data-pine-drag-handle>'
      + '<b>Untraced air</b><span class="pine-console-list-count"></span>'
      + '<button type="button" class="pine-console-list-close" aria-label="Close" title="Close">x</button>'
      + '</div><div class="pine-console-list-body"></div>';
    list.querySelector('.pine-console-list-close').addEventListener('click', function (event) {
      event.stopPropagation();
      list.remove();
    });
    document.body.appendChild(list);
    untracedRender(list);
    untracedPoll();
    if (root.PineDismiss) root.PineDismiss.watch(list, function () { list.remove(); }, [bar || el()]);
  }

  function untracedStart() {
    if (typeof document === 'undefined') return;
    untracedButton();
    untracedPoll();
    if (!untraced.timer) {
      untraced.timer = root.setInterval(function () { untracedButton(); untracedPoll(); }, UNTRACED_POLL_MS);
      if (untraced.timer && typeof untraced.timer.unref === 'function') untraced.timer.unref();
    }
  }

  function start() {
    mount();
    untracedStart();                                   /* [s3-account] */
"""

CONSOLE_EDITS = [
    ("untraced-alarm",
     "  function start() {\n    mount();\n",
     CONSOLE_JS),
    ("untraced-export",
     "    refreshTalkRestore: paintTalkRestoreButton};\n",
     "    refreshTalkRestore: paintTalkRestoreButton,\n"
     "    untraced: function () { return untracedOpen(el()); }};   /* [s3-account] */\n"),
]


def state_of(text, old, new):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == 1:
        return "ready"
    return "anchor found %d times, wanted 1; replacement found %d times" % (n_old, n_new)


def run(root, apply):
    root = Path(root)
    bad = []
    changed = 0
    for paths, edits in ((SYSTEM3, SYSTEM3_EDITS), (SCRIPT_PAGE, SCRIPT_PAGE_EDITS), (CONSOLE, CONSOLE_EDITS)):
        texts, crlf = {}, {}
        for rel in paths:
            path = root / rel
            if not path.exists():
                bad.append("%s is missing" % rel)
                continue
            raw = path.read_bytes()
            n_crlf = raw.count(b"\r\n")
            if n_crlf and n_crlf != raw.count(b"\n"):
                bad.append("%s mixes CRLF and LF lines - refusing" % rel)
                continue
            crlf[rel] = bool(n_crlf)
            texts[rel] = raw.decode("utf-8").replace("\r\n", "\n")
        if len(texts) != len(paths):
            continue
        first = texts[paths[0]]
        if any(texts[rel] != first for rel in paths[1:]):
            bad.append("%s differ before the edit - refusing to fork them further" % (paths,))
            continue
        states = {name: state_of(first, old, new) for name, old, new in edits}
        missing = ["%s (%s)" % (n, s) for n, s in states.items() if s not in ("ready", "applied")]
        if missing:
            bad.extend("%s: %s" % (paths[0], m) for m in missing)
            continue
        if all(s == "applied" for s in states.values()):
            continue
        if not apply:
            changed += sum(1 for s in states.values() if s == "ready")
            continue
        text = first
        for name, old, new in edits:
            if state_of(text, old, new) == "ready":
                text = text.replace(old, new, 1)
                changed += 1
        for rel in paths:
            data = (text.replace("\n", "\r\n") if crlf[rel] else text).encode("utf-8")
            tmp = root / (rel + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(root / rel)
    if bad:
        for b in bad:
            print("missing:", b)
        return 1
    if not changed:
        print("already applied")
        return 2
    print("APPLIED %d edit(s)" % changed if apply else "ready (%d edit(s))" % changed)
    return 0


def main(argv):
    apply = "--apply" in argv
    root = next((a for a in argv if not a.startswith("--")), ".")
    return run(root, apply)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
