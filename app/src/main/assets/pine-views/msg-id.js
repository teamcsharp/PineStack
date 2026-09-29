/* [msgid] EVERY MESSAGE HAS A CODE YOU CAN POINT AT.
 *
 * "Each message a unique hex code identifier so that way I can point them out
 *  specifically to you and ask questions about them and you're able to check
 *  into specific messages and their past and see how they ended up the way
 *  that they ended up." (operator, 2026-09-29)
 *
 * The code is the line's own id, short: a 6- or 8-hex id as it is, a 32-hex
 * spoken line by its first 8, a cue welded to a line as `<first8>-pN`. It is
 * the key every store files the line under (air log, script ledger, System 3,
 * the origin ledger, the display receipts), so `tools/why_line.py <code>` and
 * GET /api/why/{code} tell its whole story from it.
 *
 *   PineMsgId.chip(id, variant)  a small monospace "#3c4782" button; a tap
 *                                copies "#3c4782" and says "copied". variant:
 *                                'head' (the hold sheet, the line popup) or
 *                                'corner' (faint, in a Digital feed bubble)
 *   PineMsgId.find(query)        "#3c4782" or bare hex (with a digit) typed
 *                                in the find box: jump to that message and
 *                                open its hold sheet. false = not a code.
 *   PineMsgId.code(id) / parse(query) / copy(text)
 *
 * Carbon glyphs only (pineIcon). The tablet's WebView has no
 * navigator.clipboard: the kiosk bridge's copyText is the road there. */
(function (root) {
  'use strict';

  var PUNCT = /^(.*)-punct-(\d+)$/;
  var CODE = /^#?\s*([0-9a-f]{6,32})(?:-p(?:unct-)?(\d{1,3}))?$/;

  function code(id) {
    var s = String(id || '').trim().toLowerCase().replace(/^(ln|ac)-/, '');
    var m = PUNCT.exec(s);
    if (m) return code(m[1]) + '-p' + m[2];
    if (/^[0-9a-f]{9,}$/.test(s)) return s.slice(0, 8);
    return s;
  }

  /* '#3c4782' always; bare hex only with a digit in it, so a word made of
   * the letters a-f ("facade", "decade") still searches as a word. */
  function parse(query) {
    var raw = String(query || '').trim().toLowerCase().replace(/\s+/g, '');
    var hashed = raw.charAt(0) === '#';
    var m = CODE.exec(raw);
    if (!m) return null;
    if (!hashed && !/\d/.test(m[1])) return null;
    return {prefix: m[1], punct: m[2] || '', raw: raw.replace(/^#/, '')};
  }

  function matches(id, p) {
    var s = String(id || '').toLowerCase().replace(/^(ln|ac)-/, '');
    var m = PUNCT.exec(s);
    if (p.punct) return !!m && m[1].indexOf(p.prefix) === 0 && m[2] === p.punct;
    return !m && s.indexOf(p.prefix) === 0;
  }

  function glyph(name) {
    var n = document.createElement('span');
    n.className = 'pmi-ico';
    if (typeof root.pineIcon === 'function') n.innerHTML = root.pineIcon(name, '');
    else n.setAttribute('data-pine-icon', name);
    return n;
  }

  /* ------------------------------------------------------------ the toast */
  var toastNode = null;
  var toastGone = 0;
  function toast(text, bad) {
    if (!toastNode) {
      toastNode = document.createElement('div');
      toastNode.className = 'pmi-toast';
      toastNode.setAttribute('role', 'status');
      document.body.appendChild(toastNode);
    }
    toastNode.replaceChildren(glyph(bad ? 'c:search' : 'c:checkmark'), document.createTextNode(String(text || '')));
    toastNode.classList.toggle('bad', !!bad);
    toastNode.classList.add('up');
    clearTimeout(toastGone);
    toastGone = setTimeout(function () {
      if (toastNode) toastNode.classList.remove('up');
    }, bad ? 4200 : 1600);
  }

  /* ------------------------------------------------------------ the copy */
  function byHand(text) {
    try {
      var box = document.createElement('textarea');
      box.value = text;
      box.setAttribute('readonly', '');
      box.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
      document.body.appendChild(box);
      box.select();
      var ok = document.execCommand && document.execCommand('copy');
      document.body.removeChild(box);
      return !!ok;
    } catch (e) { return false; }
  }
  function bridge(text) {
    try {
      var b = root.pineDesktop;
      if (b && typeof b.copyText === 'function') return b.copyText(text) !== false;
    } catch (e) { /* no bridge */ }
    return false;
  }
  /* navigator.clipboard where the page has it; the kiosk bridge where it
   * does not (the tablet's WebView); a hidden textarea last. */
  function copy(text) {
    text = String(text || '');
    var nav = root.navigator && root.navigator.clipboard;
    if (nav && typeof nav.writeText === 'function') {
      return Promise.resolve().then(function () { return nav.writeText(text); })
        .then(function () { return true; }, function () { return bridge(text) || byHand(text); });
    }
    return Promise.resolve(bridge(text) || byHand(text));
  }

  /* ------------------------------------------------------------ the chip */
  function chip(id, variant) {
    var c = code(id);
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'pmi-chip pmi-' + (variant || 'head');
    b.title = 'Message id — tap to copy';
    b.setAttribute('aria-label', 'Message id #' + c + ' — tap to copy');
    b.setAttribute('data-msg-id', String(id || ''));
    var words = document.createElement('span');
    words.className = 'pmi-code';
    words.textContent = '#' + c;
    b.appendChild(words);
    if (variant !== 'corner') b.appendChild(glyph('c:copy--to-clipboard'));
    /* A press that STARTED here: the hold that opened the sheet under the
     * finger must not copy on its release. It acts on pointerup (a click
     * can go missing when a view repaints under the mouse - see
     * line-actions.js maybeSwallow) and the click that trails it is the
     * same press. Keys (a click with detail 0) always count. */
    var armed = false;
    var actedAt = 0;
    function act() {
      actedAt = Date.now();
      armed = false;
      copy('#' + c).then(function (ok) {
        toast(ok ? 'copied #' + c : 'could not copy - the code is #' + c, !ok);
        if (ok) {
          b.classList.add('pmi-copied');
          setTimeout(function () { b.classList.remove('pmi-copied'); }, 900);
        }
      });
    }
    var downAt = 0;
    b.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); armed = true; downAt = Date.now(); });
    b.addEventListener('pointercancel', function () { armed = false; });
    b.addEventListener('pointerup', function (ev) {
      /* a press held past the hold (600 ms) opened the sheet: not a tap */
      if (armed && Date.now() - downAt > 550) armed = false;
      if (!armed) return;
      ev.stopPropagation();
      act();
    });
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      ev.preventDefault();
      if (Date.now() - actedAt < 700) return;
      if (armed || ev.detail === 0) act();
    });
    return b;
  }

  /* ------------------------------------------------------------ find by id */
  function idOf(node) {
    if (!node || !node.getAttribute) return '';
    return String(node.getAttribute('data-line') || node.getAttribute('data-dialogue-id')
      || node.getAttribute('data-line-id') || '');
  }
  function shown(node) {
    return !!(node && (node.offsetParent || (node.getClientRects && node.getClientRects().length)));
  }
  function locate(p) {
    var all = document.querySelectorAll('[data-line], [data-dialogue-id], [data-line-id]');
    var best = null;
    for (var i = 0; i < all.length; i += 1) {
      var n = all[i];
      if (n.closest && n.closest('.la-sheet, .pmi-toast')) continue;
      if (!matches(idOf(n), p)) continue;
      if (!best || (shown(n) && !shown(best))) best = n;
      else if (shown(n) === shown(best)) best = n;          /* the later one: the newer line */
    }
    return best;
  }
  function openSheet(line) {
    var la = root.PineLineActions;
    if (!la || typeof la.open !== 'function') return false;
    la.open(line);
    return true;
  }
  function reveal(node) {
    try { node.scrollIntoView({block: 'center', behavior: 'smooth'}); } catch (e) { node.scrollIntoView(); }
    node.classList.add('pmi-flash');
    setTimeout(function () { node.classList.remove('pmi-flash'); }, 1800);
    var la = root.PineLineActions;
    var line = la && typeof la.lineAt === 'function' ? la.lineAt(node) : null;
    return openSheet(line || {id: idOf(node), said: String(node.textContent || '').trim(), node: node});
  }
  function when(at) {
    var t = Number(at || 0);
    if (!t) return '';
    var d = new Date(t * 1000);
    function two(n) { return (n < 10 ? '0' : '') + n; }
    return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
  }

  function find(query) {
    var p = parse(query);
    if (!p) return false;
    var here = locate(p);
    if (here) { reveal(here); return true; }
    var api = root.pineDesktop;
    if (!api || typeof api.get !== 'function') {
      toast('#' + p.raw + ' is not on this screen', true);
      return true;
    }
    toast('looking for #' + p.raw + '…');
    Promise.resolve(api.get('/api/why/' + encodeURIComponent(p.raw) + '?brief=1')).then(function (got) {
      var ms = (got && got.matches) || [];
      if (!ms.length) { toast('no message #' + p.raw, true); return; }
      var m = ms[0];
      var node = locate({prefix: String(m.id).replace(PUNCT, '$1'), punct: (PUNCT.exec(m.id) || [])[2] || ''});
      if (node) reveal(node);
      else openSheet({id: String(m.id), said: String(m.text || ''), node: null});
      toast(ms.length > 1
        ? ms.length + ' messages share #' + p.raw + ' - the newest (' + when(m.at) + ') is open'
        : (node ? 'found #' + code(m.id) : '#' + code(m.id) + ' is off the screen - its record (' + when(m.at) + ')'));
    }, function (err) {
      toast('the station could not look #' + p.raw + ' up: ' + String((err && err.message) || err), true);
    });
    return true;
  }

  root.PineMsgId = {code: code, parse: parse, matches: matches, chip: chip, copy: copy,
                    find: find, toast: toast};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineMsgId;
})(typeof window !== 'undefined' ? window : globalThis);
