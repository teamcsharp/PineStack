(function (root) {
  'use strict';
  var sheet = null, ticket = 0, poll = 0, previousFocus = null;
  var styleUrl = typeof document !== 'undefined' && document.currentScript && document.currentScript.src
    ? new URL('line-repeat.css', document.currentScript.src).href : '';
  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function icon(name) {
    var node = make('span', 'lr-icon');
    node.setAttribute('aria-hidden', 'true');
    node.setAttribute('data-icon', name);
    if (root.pineIcon) node.innerHTML = root.pineIcon(name);
    return node;
  }
  function button(label, symbol, fn, compact) {
    var node = make('button', compact ? 'lr-icon-button' : 'lr-command');
    node.type = 'button'; node.title = label; node.setAttribute('aria-label', label);
    node.appendChild(icon(symbol));
    if (!compact) node.appendChild(make('span', '', label));
    node.addEventListener('click', fn);
    return node;
  }
  function section(body, label) {
    var node = make('section', 'lr-section');
    node.appendChild(make('h3', '', label)); body.appendChild(node); return node;
  }
  function detail(body, label, text) {
    var node = make('details', 'lr-detail');
    node.appendChild(make('summary', '', label));
    node.appendChild(make('pre', '', typeof text === 'string' ? text : JSON.stringify(text, null, 2)));
    body.appendChild(node); return node;
  }
  function when(at) { return at ? new Date(Number(at) * 1000).toLocaleString() : 'Time unavailable'; }
  function error(err) { return String(err && (err.message || err.detail) || err); }
  function close() {
    ticket += 1; clearTimeout(poll);
    if (sheet) sheet.remove(); sheet = null;
    document.removeEventListener('keydown', keydown, true);
    if (previousFocus && previousFocus.isConnected && previousFocus.focus) previousFocus.focus();
  }
  function keydown(event) {
    if (!sheet) return;
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key !== 'Tab') return;
    var nodes = Array.from(sheet.querySelectorAll('button:not(:disabled), summary, [tabindex="0"]'));
    nodes = nodes.filter(function (n) { return n.getClientRects().length; });
    var at = nodes.indexOf(document.activeElement);
    if (nodes.length && (at < 0 || (!event.shiftKey && at === nodes.length - 1) || (event.shiftKey && at === 0))) {
      event.preventDefault(); nodes[event.shiftKey ? nodes.length - 1 : 0].focus();
    }
  }
  function watch(job, status, current) {
    clearTimeout(poll);
    poll = setTimeout(function () {
      if (current !== ticket) return;
      root.pineDesktop.get('/api/schedule/segment/generate/' + encodeURIComponent(job)).then(function (got) {
        if (current !== ticket) return;
        status.textContent = 'Fresh material: ' + got.state + (got.why ? ' - ' + got.why : '')
          + (got.state === 'done' ? ' (' + Number(got.made || 0) + ' prepared)' : '');
        if (['queued', 'waiting', 'writing'].indexOf(got.state) >= 0) watch(job, status, current);
      }, function (err) {
        if (current === ticket) status.textContent = 'Job status unavailable: ' + error(err);
      });
    }, 3000);
  }
  function paint(body, line, report, current) {
    body.replaceChildren();
    body.appendChild(make('blockquote', 'lr-quote', report.text));
    var stats = make('div', 'lr-stats');
    [[report.played_24h, 'Confirmed plays / 24h'], [report.occurrences_24h, 'Occurrences / 24h'],
      [report.writing_iterations, 'Retained writing attempts']].forEach(function (pair) {
      var stat = make('div', 'lr-stat'); stat.appendChild(make('strong', '', pair[0]));
      stat.appendChild(make('span', '', pair[1])); stats.appendChild(stat);
    });
    body.appendChild(stats);
    body.appendChild(make('p', 'lr-muted', report.coverage));
    if (report.published_unconfirmed_24h) body.appendChild(make('p', 'lr-warning',
      report.published_unconfirmed_24h + ' published occurrence(s) have no playback receipt.'));
    var causes = section(body, 'Repeat Evidence');
    (report.causes || []).forEach(function (cause) { causes.appendChild(make('p', '', cause)); });
    var actions = section(body, 'Actions');
    var status = make('p', 'lr-status', report.blocked ? 'This complete line is permanently blocked.' : '');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    var commands = make('div', 'lr-commands'), confirm = make('div', 'lr-confirm');
    var busy = false;
    function run(route, payload, trigger) {
      if (busy) return Promise.resolve();
      busy = true; trigger.disabled = true; status.textContent = 'Working...';
      return root.pineDesktop.post(route, payload).then(function (got) {
        if (current !== ticket) return;
        if (!got || got.ok === false) throw new Error(got && got.say || 'The operation was not confirmed');
        status.textContent = got.say || 'Done';
        if (got.job) watch(got.job, status, current);
        if (route === '/api/said/forget') {
          report.blocked = true; block.disabled = true;
          block.querySelector('span:last-child').textContent = 'Line blocked';
        }
      }).catch(function (err) {
        if (current === ticket) status.textContent = error(err);
      }).finally(function () {
        busy = false;
        if (current === ticket) trigger.disabled = trigger === block && report.blocked;
      });
    }
    var payload = {line_id: report.line_id, text: report.text};
    var block = button(report.blocked ? 'Line blocked' : 'Never play this line again', 'c:trash-can', function () {
      confirm.replaceChildren();
      confirm.appendChild(make('p', '', 'Permanently block this complete dialogue across future writing and playback? Prepared rounds containing it will be withdrawn. A take already delivered to a player may finish.'));
      confirm.appendChild(button('Block line', 'c:trash-can', function () {
        confirm.replaceChildren(); run('/api/said/forget', payload, block);
      }));
      confirm.appendChild(button('Cancel', 'c:close--filled', function () { confirm.replaceChildren(); }));
    });
    block.disabled = !!report.blocked; commands.appendChild(block);
    var generate = button('Generate fresh material', 'c:recycle', function () {
      run('/api/said/repeats/repair', Object.assign({action: 'generate'}, payload), generate);
    });
    generate.disabled = !report.can_generate;
    if (!report.can_generate) generate.title = report.generation_why;
    commands.appendChild(generate);
    var refresh = button('Refresh inventory and plan', 'c:renew', function () {
      run('/api/said/repeats/repair', Object.assign({action: 'refresh_plan'}, payload), refresh);
    });
    commands.appendChild(refresh);
    if (root.PineLineDeep) commands.appendChild(button('Inspect and edit source prompts', 'c:edit', function () {
      close(); root.PineLineDeep.open(Object.assign({}, line, {said: report.text}));
    }));
    actions.appendChild(commands); actions.appendChild(confirm); actions.appendChild(status);
    if (!report.can_generate) actions.appendChild(make('p', 'lr-muted', report.generation_why));
    var stock = section(body, 'Systems Holding This Line');
    (report.carriers || []).forEach(function (row) {
      detail(stock, row.system + ' / ' + row.kind + ' / ' + row.id, row);
    });
    if (!report.carriers.length) stock.appendChild(make('p', 'lr-muted', 'No matching prepared stock remains.'));
    var writing = section(body, 'Prompts and Writing Iterations');
    (report.iterations || []).forEach(function (row) {
      var fold = detail(writing, when(row.at) + ' / ' + (row.kind || 'writer') + ' / ' + (row.model || 'unknown model'),
        row.prompt || 'The prompt was not retained.');
      fold.appendChild(make('p', 'lr-muted', row.evidence));
      detail(fold, 'Sampling and prompt selection', {temperature: row.temp == null ? 'Not recorded' : row.temp,
        seed: row.seed == null ? 'Not recorded' : row.seed, prompt_hash: row.prompt_hash,
        selection: row.alternative || 'Not recorded', truncated: row.truncated});
    });
    if (!report.iterations.length) writing.appendChild(make('p', 'lr-muted', 'No retained model response can be matched to this complete line. Historical prompts cannot be reconstructed.'));
    var inputs = section(body, 'Current System Inputs');
    inputs.appendChild(make('p', 'lr-muted', 'Current configuration, not proof of the inputs used for earlier dialogue.'));
    detail(inputs, 'Schedule prompt and selection policy', report.current_prompt);
    (report.current_inputs || []).forEach(function (input) {
      detail(inputs, (input.on ? 'On: ' : 'Off: ') + input.label, input.detail || input.value || 'No value');
    });
    var history = section(body, 'Occurrence History');
    (report.history || []).forEach(function (row) {
      var at = row.heard_ack_at || row.air_at || row.ts;
      detail(history, when(at) + ' / ' + (row.heard_ack_at && row.heard_ack_by !== 'set' ? 'playback confirmed' : row.aired || 'unconfirmed')
        + ' / ' + (row.round || row.kind || 'unknown system'), row);
    });
    if (!report.history.length) history.appendChild(make('p', 'lr-muted', 'No matching occurrences in the retained ledger.'));
    if (report.omitted_history || report.omitted_iterations || report.omitted_carriers) body.appendChild(make('p', 'lr-muted',
      'Additional records omitted from this view: ' + report.omitted_history + ' occurrences, '
      + report.omitted_iterations + ' writing attempts, ' + report.omitted_carriers + ' stock entries. Counts include them.'));
  }
  function open(line) {
    close(); previousFocus = document.activeElement;
    if (styleUrl && !document.querySelector('link[data-pine-line-repeat]')) {
      var link = make('link'); link.rel = 'stylesheet'; link.href = styleUrl;
      link.setAttribute('data-pine-line-repeat', ''); document.head.appendChild(link);
    }
    sheet = make('div', 'lr-sheet'); sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true'); sheet.setAttribute('aria-label', 'Dialogue repeat diagnostics');
    var head = make('header', 'lr-head'); head.appendChild(make('h2', '', 'Dialogue repeat diagnostics'));
    var body = make('div', 'lr-body');
    function load() {
      var current = ++ticket; clearTimeout(poll);
      body.replaceChildren(make('p', '', 'Reading playback and writing records...'));
      Promise.resolve().then(function () { return root.pineDesktop.get('/api/said/repeats?line_id=' + encodeURIComponent(line.id || '')
        + '&text=' + encodeURIComponent(line.said || '')); }).then(function (report) {
        if (current === ticket && sheet) paint(body, line, report, current);
      }).catch(function (err) {
        if (current === ticket && sheet) {
          body.replaceChildren(make('p', 'lr-warning', 'Diagnostics unavailable: ' + error(err)));
          body.appendChild(button('Retry', 'c:renew', load));
        }
      });
    }
    head.appendChild(button('Refresh diagnostics', 'c:renew', load, true));
    var shut = button('Close diagnostics', 'c:close--filled', close, true); head.appendChild(shut);
    sheet.appendChild(head); sheet.appendChild(body); document.body.appendChild(sheet);
    document.addEventListener('keydown', keydown, true); shut.focus(); load();
  }
  root.PineLineRepeat = {open: open, close: close};
  if (typeof module !== 'undefined') module.exports = root.PineLineRepeat;
}(typeof window !== 'undefined' ? window : globalThis));
