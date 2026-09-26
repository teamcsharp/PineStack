(function (root) {
  'use strict';
  function make(tag, cls, text) {
    var n = document.createElement(tag); n.className = cls || '';
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function command(label, icon, run, cls) {
    var b = make('button', 'ph-command ' + (cls || '')); b.type = 'button';
    b.title = label; b.setAttribute('aria-label', label);
    b.innerHTML = root.pineIcon ? root.pineIcon(icon) : label;
    /* A command can live inside a <summary>.  Claim the press before the
       summary's native disclosure toggle sees it; otherwise a tablet tap
       opens the whole request and the icon never receives its action. */
    ['pointerdown', 'mousedown', 'touchstart'].forEach(function (name) {
      b.addEventListener(name, function (event) { event.stopPropagation(); }, true);
    });
    b.addEventListener('click', function (event) {
      event.preventDefault(); event.stopPropagation(); run(event);
    });
    return b;
  }
  function textValue(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  function detail(parent, title, value, opened) {
    var d = make('details', 'ph-detail'); d.open = !!opened;
    d.appendChild(make('summary', '', title)); d.appendChild(make('pre', '', textValue(value)));
    parent.appendChild(d); return d;
  }
  function copyText(value) {
    var text = String(value == null ? '' : value);
    /* Prompt History lives in the desktop's file:// chrome. Its copy
       commands must use Electron's Windows clipboard bridge first; the web
       clipboard is unavailable in that context on Windows. */
    try {
      if (root.pineDesktop && typeof root.pineDesktop.copyText === 'function'
          && root.pineDesktop.copyText(text)) return Promise.resolve(true);
    } catch (err) { /* keep the browser roads for served/non-desktop hosts */ }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; })
        .catch(function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  }
  function legacyCopy(text) {
    var area = document.createElement('textarea'); area.value = text; area.setAttribute('readonly', '');
    area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area); area.select();
    var copied = false;
    try { copied = !!document.execCommand('copy'); } catch (err) { copied = false; }
    finally { area.remove(); }
    return copied;
  }
  function mount(host, toolbarHost) {
    var panel = make('section', 'ph-panel'); panel.hidden = true;
    panel.setAttribute('aria-label', 'System prompt history'); host.appendChild(panel);
    var api = root.pineDesktop, nodes = [], before = 0, loading = false, epoch = 0;
    var records = Object.create(null), sectioned = false, sidebarCollapsed = false;
    var bar = make('header', 'ph-bar'), heading = make('b', '', 'System Prompt History'); bar.appendChild(heading);
    var toolbar = make('div', 'ph-toolbar');
    var models = make('select'); models.setAttribute('aria-label', 'LLM model');
    var allModels = make('option', '', 'All models'); allModels.value = ''; models.appendChild(allModels);
    var view = make('select'); view.setAttribute('aria-label', 'Prompt history view');
    ['History', 'Property nodes'].forEach(function (name) { view.appendChild(make('option', '', name)); });
    toolbar.appendChild(models); toolbar.appendChild(view); toolbar.appendChild(command('Refresh prompt history', 'c:renew', reset));
    var sections = make('label', 'ph-switch'), sectionToggle = document.createElement('input'); sectionToggle.type = 'checkbox';
    sectionToggle.setAttribute('aria-label', 'Display prompt as expandable sections'); sections.appendChild(sectionToggle); sections.appendChild(make('span', '', 'Sections')); toolbar.appendChild(sections);
    var collapse = command('Collapse property sidebar', 'c:caret--left', function () {
      sidebarCollapsed = !sidebarCollapsed; panel.classList.toggle('ph-sidebar-collapsed', sidebarCollapsed);
      collapse.title = sidebarCollapsed ? 'Expand property sidebar' : 'Collapse property sidebar'; collapse.setAttribute('aria-label', collapse.title);
    });
    var exitFullscreen = make('button', 'ph-exit-fullscreen', 'Exit prompt fullscreen'); exitFullscreen.type = 'button'; exitFullscreen.hidden = true;
    var setFullscreen = function (on) {
      on = !!on;
      panel.classList.toggle('ph-fullscreen', on); fullscreen.hidden = on; exitFullscreen.hidden = !on;
      /* The bar normally lives in the Script header. A fixed fullscreen
         panel sits above that header, so carry the bar into the panel while
         expanded and put it back in its dock on exit. */
      if (on) panel.insertBefore(bar, panel.firstChild);
      else if (toolbarHost) toolbarHost.appendChild(bar);
      fullscreen.title = 'Fullscreen system prompt history'; fullscreen.setAttribute('aria-label', fullscreen.title);
    };
    var fullscreen = command('Fullscreen system prompt history', 'c:maximize', function () { setFullscreen(true); });
    exitFullscreen.addEventListener('click', function () { setFullscreen(false); });
    toolbar.appendChild(collapse); toolbar.appendChild(fullscreen); toolbar.appendChild(exitFullscreen); bar.appendChild(toolbar);
    var layout = make('div', 'ph-layout'), main = make('div', 'ph-main'), sidebar = make('aside', 'ph-sidebar');
    var notice = make('p', 'ph-notice'); notice.setAttribute('role', 'status'); var list = make('div', 'ph-calls');
    var more = make('button', 'ph-more', 'Older requests'); more.type = 'button'; more.addEventListener('click', load);
    var graph = make('div', 'ph-nodes'); graph.hidden = true;
    if (toolbarHost) toolbarHost.appendChild(bar); else panel.appendChild(bar);
    panel.promptBar = bar;
    panel.appendChild(layout); layout.appendChild(main); layout.appendChild(sidebar);
    main.appendChild(notice); main.appendChild(list); main.appendChild(more); main.appendChild(graph);
    var search = make('input'); search.type = 'search'; search.placeholder = 'Filter properties'; search.setAttribute('aria-label', 'Filter prompt properties');
    var group = make('select'); group.setAttribute('aria-label', 'Property group'); var choices = make('div', 'ph-properties'), editor = make('div', 'ph-editor');
    sidebar.appendChild(search); sidebar.appendChild(group); sidebar.appendChild(choices); sidebar.appendChild(editor);
    models.addEventListener('change', reset); search.addEventListener('input', propertyList); group.addEventListener('change', propertyList);
    view.addEventListener('change', function () { graph.hidden = view.value !== 'Property nodes'; list.hidden = !graph.hidden; more.hidden = !graph.hidden || !before; });
    sectionToggle.addEventListener('change', function () {
      sectioned = sectionToggle.checked;
      Object.keys(records).forEach(function (id) {
        var call = Array.prototype.slice.call(list.querySelectorAll('.ph-call')).find(function (item) { return item.dataset.id === id; });
        if (call && call.open) renderRequest(call, records[id]);
      });
    });
    function propertyList() {
      choices.replaceChildren(); nodes.filter(function (n) {
        return (!group.value || n.group === group.value) && (n.label + ' ' + n.path.join('.')).toLowerCase().includes(search.value.toLowerCase());
      }).forEach(function (n) {
        var row = make('div', 'ph-property'), select = make('button', '', n.label); select.type = 'button'; select.title = n.path.join('.');
        select.addEventListener('click', function () { edit(n); }); row.appendChild(select);
        if (n.random) row.appendChild(command('Randomization: ' + n.label, 'm:casino', function () { dice(n); })); choices.appendChild(row);
      });
    }
    function dice(n) {
      var popup = make('dialog', 'ph-dice'); popup.setAttribute('aria-label', 'Randomization: ' + n.label); popup.appendChild(make('h3', '', n.label));
      popup.appendChild(make('p', '', n.random.distribution)); popup.appendChild(make('p', '', n.random.min + ': ' + n.random.low)); popup.appendChild(make('p', '', n.random.max + ': ' + n.random.high));
      var customize = make('button', '', 'Customize property'); customize.type = 'button'; customize.addEventListener('click', function () { popup.close(); edit(n); }); popup.appendChild(customize);
      popup.appendChild(command('Close randomization', 'c:close--filled', function () { popup.close(); })); popup.addEventListener('close', function () { popup.remove(); }); panel.appendChild(popup); popup.showModal();
    }
    function edit(n, draft) {
      editor.replaceChildren(); editor.appendChild(make('h3', '', n.label)); var input = make(n.type === 'select' ? 'select' : n.type === 'text' || n.type === 'json' ? 'textarea' : 'input'); input.setAttribute('aria-label', n.label);
      if (n.type === 'select') (n.choices || []).forEach(function (v) { input.appendChild(make('option', '', v)); });
      if (n.type === 'checkbox') { input.type = 'checkbox'; input.checked = n.value; } else { if (n.type === 'number') { input.type = 'number'; ['min', 'max', 'step'].forEach(function (key) { if (n[key] !== undefined) input[key] = n[key]; }); } input.value = draft !== undefined ? draft : n.type === 'json' ? JSON.stringify(n.value, null, 2) : n.value; }
      editor.appendChild(input); var status = make('p', 'ph-notice'); status.setAttribute('role', 'status');
      var save = command('Save future prompt property', 'c:save', function () {
        var value; try { value = n.type === 'checkbox' ? input.checked : n.type === 'number' ? Number(input.value) : n.type === 'json' ? JSON.parse(input.value) : input.value; if (!input.checkValidity() || (n.type === 'number' && (!input.value.trim() || !Number.isFinite(value)))) throw new Error('Enter a valid value'); } catch (err) { status.textContent = err.message; return; }
        save.disabled = true; api.post('/api/prompt-history/config', {path:n.path, was:n.value, value:value}).then(function (result) { n.value = result.value; status.textContent = result.say; }).catch(function (err) { status.textContent = err.message; }).finally(function () { save.disabled = false; });
      }); editor.appendChild(save); editor.appendChild(status); input.focus();
    }
    function sourceEditor(text) {
      editor.replaceChildren(); editor.appendChild(make('h3', '', 'Future prompt source')); var selectSource = make('select'); selectSource.setAttribute('aria-label', 'Future prompt source');
      nodes.filter(function (n) { return n.type === 'text'; }).forEach(function (n) { var o = make('option', '', n.label); o.value = JSON.stringify(n.path); selectSource.appendChild(o); }); editor.appendChild(selectSource);
      var choose = make('button', '', 'Open draft'); choose.type = 'button'; choose.addEventListener('click', function () { var n = nodes.find(function (node) { return JSON.stringify(node.path) === selectSource.value; }); if (n) edit(n, text); }); editor.appendChild(choose); selectSource.focus();
    }
    function promptContent(parent, value) {
      var text = textValue(value); if (!sectioned) { parent.appendChild(make('pre', 'ph-prompt-text', text)); return; }
      text.split(/\n\s*\n/).filter(Boolean).forEach(function (part, index) { var head = String(part).split('\n')[0].replace(/[:.].*$/, '').trim(); var block = make('details', 'ph-prompt-section'); block.appendChild(make('summary', '', head && head.length < 54 ? head : 'Prompt section ' + (index + 1))); block.appendChild(make('pre', '', part)); parent.appendChild(block); });
    }
    function pop(title) {
      var popup = make('dialog', 'ph-inspect'); popup.setAttribute('aria-label', title); popup.appendChild(make('h3', '', title)); popup.appendChild(command('Close inspection', 'c:close--filled', function () { popup.close(); }, 'ph-inspect-close')); popup.addEventListener('close', function () { popup.remove(); }); panel.appendChild(popup); popup.showModal(); return popup;
    }
    function matchingNodes(value) {
      var text = String(value || '').toLowerCase(); var matched = nodes.filter(function (node) { return text.includes(String(node.label || '').toLowerCase()) || (typeof node.value === 'string' && node.value && text.includes(node.value.toLowerCase())); }); return matched.length ? matched : nodes.slice(0, 12);
    }
    function trace(value, got) {
      var popup = pop('Prompt property trace'); detail(popup, 'Selected injected value', value, true); detail(popup, 'Dispatch-time property snapshot', got.properties || {}); popup.appendChild(make('p', 'ph-notice', got.properties_evidence || 'The snapshot shows the settings observed when this local request was dispatched.'));
      var path = make('div', 'ph-trace-path'); path.appendChild(make('b', '', 'Origin path')); ['Configured property', 'System prompt assembly', 'Local LLM request', 'Generated output'].forEach(function (name) { path.appendChild(make('span', '', name)); }); popup.appendChild(path);
      matchingNodes(value).forEach(function (node) { var row = make('div', 'ph-trace-node'); row.appendChild(make('b', '', node.label)); row.appendChild(make('small', '', node.path.join('.'))); row.appendChild(command('Edit ' + node.label, 'c:edit', function () { popup.close(); edit(node); })); if (node.type === 'checkbox') row.appendChild(command('Disable ' + node.label, 'c:close--filled', function () { api.post('/api/prompt-history/config', {path:node.path, was:node.value, value:false}).then(function (result) { node.value = result.value; row.dataset.state = 'disabled'; }); })); if (node.type === 'text') row.appendChild(command('Clear ' + node.label, 'c:trash-can', function () { api.post('/api/prompt-history/config', {path:node.path, was:node.value, value:''}).then(function (result) { node.value = result.value; row.dataset.state = 'cleared'; }); })); popup.appendChild(row); });
    }
    function conversation(got) {
      var popup = pop('Prompt conversation'), request = got.request || {}, messages = request.messages || [{role:'prompt', content:request.prompt || ''}]; if (request.system) messages = [{role:'system', content:request.system}].concat(messages);
      messages.forEach(function (message) { var bubble = make('article', 'ph-bubble ' + String(message.role || 'message')); bubble.appendChild(make('b', '', message.role || 'message')); bubble.appendChild(make('pre', '', textValue(message.content || message))); popup.appendChild(bubble); }); var response = got.response || {}, output = response.response || response.output || response.text || response; var final = make('article', 'ph-bubble output'); final.appendChild(make('b', '', 'output')); final.appendChild(make('pre', '', textValue(output))); popup.appendChild(final);
    }
    function nodeView(got) {
      var popup = pop('Prompt execution node view'); popup.appendChild(make('p', 'ph-notice', 'The request is connected to the configuration captured at dispatch. Select a property node to edit the value used for future prompts.')); var graphView = make('div', 'ph-execution-graph'); ['Prompt properties', 'System prompt', 'LLM ' + String((got.request || {}).model || ''), 'Response'].forEach(function (name) { graphView.appendChild(make('span', '', name)); }); popup.appendChild(graphView); matchingNodes(JSON.stringify(got.properties || {})).forEach(function (node) { var b = make('button', '', node.label); b.type = 'button'; b.addEventListener('click', function () { popup.close(); edit(node); }); popup.appendChild(b); }); detail(popup, 'Observed properties', got.properties || {}, true);
    }
    function requestBody(got) {
      var body = make('div', 'ph-call-body'), request = got.request || {}, messages = request.messages || [{role:'prompt', content:request.prompt || ''}]; if (request.system) messages = [{role:'system', content:request.system}].concat(messages);
      messages.forEach(function (message) { var messageBox = make('section', 'ph-message'); messageBox.appendChild(make('b', '', message.role || 'message')); var actions = make('span', 'ph-message-actions'); if (message.role === 'system') actions.appendChild(command('Copy system prompt', 'c:copy--to-clipboard', function () { copyText(message.content).then(function (copied) { notice.textContent = copied ? 'System prompt copied to the Windows clipboard.' : 'The Windows clipboard refused the system prompt.'; }); })); if (typeof message.content === 'string') actions.appendChild(command('Edit future source', 'c:edit', function () { sourceEditor(message.content); })); actions.appendChild(command('Trace this prompt value', 'c:chart--network', function () { trace(message.content || message, got); })); messageBox.appendChild(actions); promptContent(messageBox, message.content || message); var hold = 0; messageBox.addEventListener('pointerdown', function (event) { if (event.button !== 0) return; hold = root.setTimeout(function () { hold = 0; trace(message.content || message, got); }, 600); }); ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (name) { messageBox.addEventListener(name, function () { if (hold) root.clearTimeout(hold); hold = 0; }); }); messageBox.addEventListener('contextmenu', function (event) { event.preventDefault(); trace(message.content || message, got); }); body.appendChild(messageBox); });
      detail(body, 'Sampling and request options', Object.assign({}, request, {messages:undefined, prompt:undefined, system:undefined})); detail(body, 'Output / conversation', got.response, true); detail(body, 'Properties observed at dispatch', got.properties || {}); body.appendChild(make('p', 'ph-notice', got.properties_evidence || '')); if (got.error) body.appendChild(make('p', 'ph-notice', got.error)); return body;
    }
    function renderRequest(call, got) { var old = call.querySelector('.ph-call-body'); if (old) old.remove(); call.appendChild(requestBody(got)); }
    function fetchRecord(row, after) { if (records[row.id]) { after(records[row.id]); return; } api.get('/api/prompt-history/' + encodeURIComponent(row.id)).then(function (got) { records[row.id] = got; after(got); }).catch(function (err) { notice.textContent = err.message; }); }
    function requestRow(row) {
      var d = make('details', 'ph-call'); d.dataset.id = row.id; var summary = make('summary'); summary.appendChild(make('b', '', row.model + ' / ' + row.purpose)); summary.appendChild(make('time', '', new Date(row.at * 1000).toLocaleString() + ' / ' + row.state)); summary.appendChild(make('span', '', row.preview)); var actions = make('span', 'ph-call-actions'); actions.appendChild(command('Open prompt execution in node view', 'c:chart--network', function (event) { event.preventDefault(); event.stopPropagation(); fetchRecord(row, nodeView); })); actions.appendChild(command('Open prompt conversation', 'c:chat', function (event) { event.preventDefault(); event.stopPropagation(); fetchRecord(row, conversation); })); d.appendChild(summary); d.appendChild(actions); d.addEventListener('toggle', function () { if (d.open) fetchRecord(row, function (got) { renderRequest(d, got); }); }); return d;
    }
    function load() {
      if (loading) return; loading = true; more.disabled = true; var current = epoch;
      api.get('/api/prompt-history?limit=30&before=' + before + '&model=' + encodeURIComponent(models.value)).then(function (got) { if (current !== epoch || !panel.isConnected) return; notice.textContent = got.capture_error || got.coverage; var selected = models.value; models.replaceChildren(); var all = make('option', '', 'All models'); all.value = ''; models.appendChild(all); (got.models || []).forEach(function (model) { models.appendChild(make('option', '', model)); }); models.value = selected; (got.rows || []).forEach(function (row) { list.appendChild(requestRow(row)); }); before = got.next || 0; more.hidden = !before || !graph.hidden; if (!list.childElementCount) notice.textContent += ' No requests recorded yet.'; }).catch(function (err) { if (current === epoch) notice.textContent = err.message; }).finally(function () { if (current === epoch) { loading = false; more.disabled = false; } });
    }
    function config() {
      api.get('/api/prompt-history/config').then(function (got) { nodes = got.nodes || []; group.replaceChildren(); var all = make('option', '', 'All properties'); all.value = ''; group.appendChild(all); Array.from(new Set(nodes.map(function (n) { return n.group; }))).forEach(function (name) { group.appendChild(make('option', '', name)); }); graph.replaceChildren(); (got.roles || []).forEach(function (role) { var node = make('section', 'ph-node'); node.appendChild(make('h3', '', role.name)); node.appendChild(make('p', '', (role.systems || []).join(', '))); nodes.filter(function (n) { return n.path.includes(role.id) || n.path.join('.').includes(role.id + '_') || n.path[1] === (role.id === 'host' ? 'persona' : role.id + '_persona'); }).forEach(function (n) { var b = make('button', '', n.label); b.type = 'button'; b.addEventListener('click', function () { edit(n); }); node.appendChild(b); }); graph.appendChild(node); }); propertyList(); }).catch(function (err) { editor.textContent = err.message; });
    }
    function reset() { epoch += 1; before = 0; loading = false; records = Object.create(null); list.replaceChildren(); load(); config(); }
    panel.reload = reset; panel.setFullscreen = setFullscreen; return panel;
  }
  root.PinePromptHistory = {toggle: function (host, trigger, toolbarHost) { var panel = host.querySelector('.ph-panel') || mount(host, toolbarHost); panel.hidden = !panel.hidden; if (panel.hidden && panel.setFullscreen) panel.setFullscreen(false); if (panel.promptBar) panel.promptBar.hidden = panel.hidden; host.classList.toggle('ph-active', !panel.hidden); trigger.setAttribute('aria-pressed', String(!panel.hidden)); if (!panel.hidden) panel.reload(); }};
}(window));
