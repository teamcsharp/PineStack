/* The Gazette in the Script pane. Reads only on opening, refreshing or selecting
 * an issue; no timer and no feed subscription. The screenplay remains mounted. */
(function (root) {
  'use strict';
  var remembered = '';
  function issuesOf(payload) {
    var seen = new Set();
    return (Array.isArray(payload && payload.editions) ? payload.editions : [])
      .filter(function (row) {
        var id = String(row && row.id || '');
        if (!id || seen.has(id)) return false;
        seen.add(id); return true;
      }).map(function (row) { return Object.assign({}, row, {id: String(row.id)}); })
      .sort(function (a, b) {
        return Number(a.since || a.at || 0) - Number(b.since || b.at || 0)
          || a.id.localeCompare(b.id);
      });
  }
  function indexAt(x, left, width, count) {
    if (count < 2 || !(width > 0)) return 0;
    return Math.max(0, Math.min(count - 1, Math.round((x - left) / width * (count - 1))));
  }
  function when(row) {
    var seconds = Number(row && (row.since || row.at) || 0);
    if (!(seconds > 0)) return 'Issue ' + String(row && row.id || '');
    return new Date(seconds * 1000).toLocaleString(undefined,
      {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})
      + (String(row.id).indexOf('x') >= 0 ? ' \u00b7 extra' : '');
  }
  function escape(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function documentFor(html, base) {
    var tag = '<base href="' + escape(String(base || '').replace(/\/+$/, '') + '/') + '">';
    return /<head(?:\s[^>]*)?>/i.test(html)
      ? html.replace(/<head(?:\s[^>]*)?>/i, function (head) { return head + tag; })
      : '<!doctype html><html><head>' + tag + '</head><body>' + html + '</body></html>';
  }
  function mount(options) {
    var doc = root.document, parent = options.parent, titleRow = options.titleRow;
    var active = false, disposed = false, list = [], current = '', epoch = 0, shelfEpoch = 0;
    var loadingShelf = null, style = 'broadsheet', preview = null, dragging = false;
    var cache = new Map(), scriptTop = null;
    try { style = root.localStorage.getItem('paperStyle') === 'tabloid' ? 'tabloid' : 'broadsheet'; }
    catch (error) { /* a private store still reads the paper */ }
    function make(tag, cls, text) {
      var node = doc.createElement(tag); node.className = cls || '';
      if (text != null) node.textContent = text;
      return node;
    }
    function button(cls, text, label, action) {
      var node = make('button', cls, text); node.type = 'button'; node.title = label;
      node.setAttribute('aria-label', label); node.addEventListener('click', action); return node;
    }
    var toggle = button('sp-band-reopen sp-band-always sp-gazette-toggle', '\uD83D\uDCF0',
      'Gazette view: read an issue here; tap again to return to the script', function () { setActive(!active); });
    toggle.id = 'spGazetteToggle'; toggle.setAttribute('aria-pressed', 'false');
    if (options.icon) toggle.innerHTML = options.icon;
    options.toolbar.appendChild(toggle);
    var title = button('sp-gazette-title', 'The Gazette \u00b7 reading the shelf\u2026',
      'Choose a Gazette issue; slide across this top bar to scrub older to newer', function () {
        if (dragging) return;
        shelf.hidden = !shelf.hidden;
        title.setAttribute('aria-expanded', String(!shelf.hidden));
        if (!shelf.hidden) { refreshShelf(true); choose.focus(); }
      });
    title.hidden = true; title.setAttribute('aria-expanded', 'false');
    title.setAttribute('aria-controls', 'spGazetteShelf'); titleRow.insertBefore(title, titleRow.firstChild);
    var pane = make('section', 'sp-gazette'); pane.id = 'spGazette'; pane.hidden = true;
    pane.setAttribute('aria-label', 'Pine Box Gazette reader');
    var shelf = make('div', 'sp-gazette-shelf'); shelf.id = 'spGazetteShelf'; shelf.hidden = true;
    var choose = make('select', 'sp-gazette-issues'); choose.setAttribute('aria-label', 'Gazette issue archive');
    choose.addEventListener('change', function () { preview = null; show(choose.value); shelf.hidden = true; title.setAttribute('aria-expanded', 'false'); });
    shelf.appendChild(choose);
    shelf.appendChild(button('sp-gazette-refresh', '\u21bb', 'Refresh the Gazette issue archive', function () { refreshShelf(true); }));
    var bar = make('div', 'sp-gazette-bar');
    var oldest = button('', '\u23ee', 'Oldest Gazette issue', function () { select(0); });
    var older = button('', '\u2039', 'Previous Gazette issue', function () { select(position() - 1); });
    var newer = button('', '\u203a', 'Next Gazette issue', function () { select(position() + 1); });
    var newest = button('', '\u23ed', 'Newest Gazette issue', function () { select(list.length - 1); });
    var scrub = make('input', 'sp-gazette-scrub'); scrub.type = 'range'; scrub.min = '0'; scrub.step = '1';
    scrub.setAttribute('aria-label', 'Scrub Gazette issues: oldest on the left, newest on the right');
    scrub.title = 'Slide to preview any issue, then release to read it';
    var count = make('span', 'sp-gazette-count'); count.setAttribute('aria-live', 'polite');
    scrub.addEventListener('input', function () { preview = Number(scrub.value); paint(); });
    scrub.addEventListener('change', function () { var index = Number(scrub.value); preview = null; select(index); });
    [oldest, older, scrub, newer, newest, count].forEach(function (node) { bar.appendChild(node); });
    var styles = make('div', 'sp-gazette-styles');
    var newspaper = button('', 'Newspaper', 'Read this issue as a newspaper', function () { setStyle('broadsheet'); });
    var tabloid = button('', 'Tabloid', 'Read this issue as a tabloid', function () { setStyle('tabloid'); });
    styles.appendChild(newspaper); styles.appendChild(tabloid);
    var status = make('span', 'sp-gazette-status'); status.setAttribute('role', 'status');
    styles.appendChild(status);
    styles.appendChild(button('sp-gazette-back', 'Script', 'Return to the script', function () { setActive(false); toggle.focus(); }));
    var frame = make('iframe', 'sp-gazette-frame'); frame.title = 'Pine Box Gazette issue';
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-popups');
    pane.appendChild(shelf); pane.appendChild(bar); pane.appendChild(styles); pane.appendChild(frame); parent.appendChild(pane);
    function position() { return list.findIndex(function (row) { return row.id === current; }); }
    function paint() {
      var index = preview == null ? position() : preview, row = list[index];
      if (row) title.textContent = 'The Gazette \u00b7 ' + when(row) + (row.headline ? ' \u00b7 ' + row.headline : '');
      else title.textContent = list.length ? 'The Gazette \u00b7 choose an issue' : 'The Gazette \u00b7 no published issues yet';
      title.title = (row ? when(row) + (row.headline ? '\n' + row.headline : '') + '\n' : '')
        + 'Tap to choose an issue. Drag left to older issues, right to newer.';
      scrub.max = String(Math.max(0, list.length - 1)); scrub.disabled = list.length < 2;
      scrub.value = String(Math.max(0, index));
      scrub.setAttribute('aria-valuetext', row ? when(row) + ' \u00b7 ' + (row.headline || row.id) : 'No issues');
      count.textContent = list.length ? String(Math.max(0, index) + 1) + ' / ' + list.length : '0 issues';
      oldest.disabled = older.disabled = index <= 0;
      newer.disabled = newest.disabled = index < 0 || index >= list.length - 1;
      choose.value = current;
      newspaper.setAttribute('aria-pressed', String(style === 'broadsheet'));
      tabloid.setAttribute('aria-pressed', String(style === 'tabloid'));
    }
    function select(index) {
      if (!list.length) return;
      index = Math.max(0, Math.min(list.length - 1, index)); preview = null;
      show(list[index].id);
    }
    async function show(id, force) {
      if (!id || disposed || !active) return;
      current = id; remembered = id; preview = null; paint();
      var mine = ++epoch, key = id + ':' + style, snapshotStyle = style;
      status.textContent = 'Reading issue\u2026'; frame.setAttribute('aria-busy', 'true');
      try {
        var html = !force && cache.get(key);
        if (!html) {
          var got = await options.request('/api/paper/' + encodeURIComponent(id) + '/view?style=' + snapshotStyle);
          if (!got || got.id !== id || typeof got.html !== 'string') throw new Error('The Gazette did not return this issue.');
          html = got.html; cache.set(key, html);
          while (cache.size > 8) cache.delete(cache.keys().next().value);
        }
        if (disposed || !active || mine !== epoch) return;
        frame.title = 'Pine Box Gazette \u00b7 ' + when(list.find(function (row) { return row.id === id; })) + ' \u00b7 ' + snapshotStyle;
        frame.srcdoc = documentFor(html, options.url('/'));
        status.textContent = '';
      } catch (error) {
        if (disposed || !active || mine !== epoch) return;
        status.textContent = String(error && error.message || error).slice(0, 180);
        frame.srcdoc = '<p style="font:16px Georgia;padding:24px">This issue could not open. Refresh the archive to retry.</p>';
      } finally { if (mine === epoch) frame.setAttribute('aria-busy', 'false'); }
    }
    function setStyle(value) {
      if (style === value) return; style = value;
      try { root.localStorage.setItem('paperStyle', style); } catch (error) { /* optional */ }
      paint(); if (current) show(current);
    }
    function refreshShelf(force) {
      if (loadingShelf) return loadingShelf;
      var mine = ++shelfEpoch; status.textContent = 'Reading issue archive\u2026';
      loadingShelf = Promise.resolve().then(function () { return options.request('/api/paper'); })
        .then(function (got) {
          if (disposed || mine !== shelfEpoch) return;
          list = issuesOf(got); choose.replaceChildren();
          list.slice().reverse().forEach(function (row) {
            var item = make('option', '', when(row) + ' \u00b7 ' + (row.headline || row.id)); item.value = row.id; choose.appendChild(item);
          });
          var id = list.some(function (row) { return row.id === current; }) ? current
            : list.some(function (row) { return row.id === remembered; }) ? remembered
            : list.length ? list[list.length - 1].id : '';
          current = id; paint();
          if (id && active) return show(id, force);
          status.textContent = list.length ? '' : 'The next published issue will appear here.';
        }).catch(function (error) {
          if (!disposed && mine === shelfEpoch) status.textContent = String(error && error.message || error).slice(0, 180);
        }).finally(function () { loadingShelf = null; });
      return loadingShelf;
    }
    function setActive(on) {
      if (disposed || active === !!on) return;
      active = !!on; epoch += 1;
      toggle.setAttribute('aria-pressed', String(active)); title.hidden = !active; pane.hidden = !active;
      options.host.classList.toggle('sp-gazette-on', active);
      if (active) {
        scriptTop = options.script ? options.script.scrollTop : null;
        if (options.enter) options.enter();
        if (!list.length) refreshShelf(false); else if (current) show(current);
      } else {
        preview = null; shelf.hidden = true; title.setAttribute('aria-expanded', 'false');
        /* No copy of the screenplay is made and no script event is injected. */
        if (options.leave) options.leave(scriptTop);
        else if (options.script && scriptTop != null) options.script.scrollTop = scriptTop;
        scriptTop = null;
        /* Release the newspaper's decoder and audio while the script is on show. */
        frame.srcdoc = ''; status.textContent = '';
      }
    }
    title.addEventListener('pointerdown', function (event) {
      if (!active || list.length < 2 || event.button > 0) return;
      var box = title.getBoundingClientRect();
      dragging = false; title._gazettePointer = {id: event.pointerId, x: event.clientX, left: box.left, width: box.width};
      title.setPointerCapture(event.pointerId);
    });
    title.addEventListener('pointermove', function (event) {
      var point = title._gazettePointer; if (!point || point.id !== event.pointerId) return;
      if (Math.abs(event.clientX - point.x) > 8) dragging = true;
      if (dragging) { preview = indexAt(event.clientX, point.left, point.width, list.length); paint(); }
    });
    function finish(event, commit) {
      var point = title._gazettePointer; if (!point || point.id !== event.pointerId) return;
      title._gazettePointer = null;
      if (title.hasPointerCapture(event.pointerId)) title.releasePointerCapture(event.pointerId);
      if (dragging) {
        event.preventDefault(); if (commit && preview != null) select(preview); else { preview = null; paint(); }
        /* suppress the synthetic click following the scrub gesture */
        root.setTimeout(function () { dragging = false; }, 0);
      }
    }
    title.addEventListener('pointerup', function (event) { finish(event, true); });
    title.addEventListener('pointercancel', function (event) { finish(event, false); });
    function keys(event) {
      if (!active) return;
      if (event.key === 'Escape') { event.preventDefault(); setActive(false); toggle.focus(); return; }
      if (event.target === choose || event.target === scrub) return;
      var index = position();
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') index -= 1;
      else if (event.key === 'ArrowRight' || event.key === 'PageDown') index += 1;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = list.length - 1;
      else return;
      event.preventDefault(); select(index);
    }
    title.addEventListener('keydown', keys); pane.addEventListener('keydown', keys);
    paint();
    return {setActive: setActive, close: function () { setActive(false); },
      refresh: function () { return refreshShelf(true); }, active: function () { return active; },
      select: select, state: function () { return {active: active, current: current, style: style, issues: list.map(function (row) { return row.id; })}; },
      dispose: function () {
        setActive(false); disposed = true; epoch += 1; shelfEpoch += 1;
        frame.srcdoc = ''; pane.remove(); title.remove(); toggle.remove(); cache.clear();
      }};
  }
  root.PineGazetteView = {mount: mount, issuesOf: issuesOf, indexAt: indexAt, when: when, documentFor: documentFor};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineGazetteView;
})(typeof window !== 'undefined' ? window : globalThis);
