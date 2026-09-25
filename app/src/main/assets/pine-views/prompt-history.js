(function (root) {
  'use strict';
  function make(tag, cls, text) {
    var n = document.createElement(tag); n.className = cls || '';
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function button(label, icon, run) {
    var b = make('button', 'ph-command'); b.type = 'button'; b.title = label; b.setAttribute('aria-label', label);
    b.innerHTML = root.pineIcon ? root.pineIcon(icon) : '';
    b.addEventListener('click', run); return b;
  }
  function detail(parent, title, value, opened) {
    var d = make('details', 'ph-detail'); d.open = !!opened; d.appendChild(make('summary', '', title));
    d.appendChild(make('pre', '', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    parent.appendChild(d); return d;
  }
  function mount(host) {
    var panel = make('section', 'ph-panel'); panel.hidden = true;
    panel.setAttribute('aria-label', 'System prompt history'); host.appendChild(panel);
    var api = root.pineDesktop, nodes = [], before = 0, loading = false, epoch = 0;
    var bar = make('header', 'ph-bar'); bar.appendChild(make('b', '', 'System Prompt History'));
    var models = make('select'); models.setAttribute('aria-label', 'LLM model');
    models.appendChild(make('option', '', 'All models')); models.firstChild.value = '';
    bar.appendChild(models); bar.appendChild(button('Refresh prompt history', 'c:renew', reset));
    var layout = make('div', 'ph-layout'), main = make('div', 'ph-main'), sidebar = make('aside', 'ph-sidebar');
    var notice = make('p', 'ph-notice'); notice.setAttribute('role', 'status');
    var list = make('div', 'ph-calls');
    var more = make('button', 'ph-more', 'Older requests'); more.type = 'button'; more.addEventListener('click', load);
    var view = make('select'); view.setAttribute('aria-label', 'Prompt view');
    ['History', 'Property nodes'].forEach(function (name) { var o = make('option', '', name); view.appendChild(o); });
    bar.appendChild(view); panel.appendChild(bar); panel.appendChild(layout);
    main.appendChild(notice); main.appendChild(list); main.appendChild(more); layout.appendChild(main); layout.appendChild(sidebar);
    var graph = make('div', 'ph-nodes'); graph.hidden = true; main.appendChild(graph);
    var search = make('input'); search.type = 'search'; search.placeholder = 'Filter properties'; search.setAttribute('aria-label', 'Filter prompt properties');
    var group = make('select'); group.setAttribute('aria-label', 'Property group');
    sidebar.appendChild(search); sidebar.appendChild(group);
    var choices = make('div', 'ph-properties'); sidebar.appendChild(choices);
    var editor = make('div', 'ph-editor'); sidebar.appendChild(editor);
    var selectSource = make('select'); selectSource.setAttribute('aria-label', 'Future prompt source');
    var sourceDraft = '';
    models.addEventListener('change', reset);
    search.addEventListener('input', propertyList); group.addEventListener('change', propertyList);
    view.addEventListener('change', function () {
      graph.hidden = view.value !== 'Property nodes'; list.hidden = !graph.hidden; more.hidden = !graph.hidden || !before;
    });
    function propertyList() {
      choices.replaceChildren();
      nodes.filter(function (n) {
        return (!group.value || n.group === group.value) && (n.label + ' ' + n.path.join('.')).toLowerCase().includes(search.value.toLowerCase());
      }).forEach(function (n) {
        var row = make('div', 'ph-property');
        var select = make('button', '', n.label); select.type = 'button'; select.title = n.path.join('.');
        select.addEventListener('click', function () { edit(n); }); row.appendChild(select);
        if (n.random) row.appendChild(button('Randomization: ' + n.label, 'm:casino', function () { dice(n); }));
        choices.appendChild(row);
      });
    }
    function dice(n) {
      var popup = make('dialog', 'ph-dice'); popup.setAttribute('aria-label', 'Randomization: ' + n.label);
      popup.appendChild(make('h3', '', n.label)); popup.appendChild(make('p', '', n.random.distribution));
      popup.appendChild(make('p', '', n.random.min + ': ' + n.random.low)); popup.appendChild(make('p', '', n.random.max + ': ' + n.random.high));
      var customize = make('button', '', 'Customize property'); customize.type = 'button';
      customize.addEventListener('click', function () { popup.close(); edit(n); }); popup.appendChild(customize);
      popup.appendChild(button('Close randomization', 'c:close--filled', function () { popup.close(); }));
      popup.addEventListener('close', function () { popup.remove(); }); panel.appendChild(popup); popup.showModal();
    }
    function edit(n, draft) {
      editor.replaceChildren(); editor.appendChild(make('h3', '', n.label));
      var input = make(n.type === 'select' ? 'select' : n.type === 'text' || n.type === 'json' ? 'textarea' : 'input');
      input.setAttribute('aria-label', n.label);
      if (n.type === 'select') (n.choices || []).forEach(function (v) { input.appendChild(make('option', '', v)); });
      if (n.type === 'checkbox') { input.type = 'checkbox'; input.checked = n.value; }
      else {
        if (n.type === 'number') { input.type = 'number'; ['min','max','step'].forEach(function (key) { if (n[key] !== undefined) input[key] = n[key]; }); }
        input.value = draft !== undefined ? draft : n.type === 'json' ? JSON.stringify(n.value, null, 2) : n.value;
      }
      editor.appendChild(input); var status = make('p', 'ph-notice'); status.setAttribute('role', 'status');
      var save = button('Save future prompt property', 'c:save', function () {
        var value;
        try {
          value = n.type === 'checkbox' ? input.checked : n.type === 'number' ? Number(input.value) : n.type === 'json' ? JSON.parse(input.value) : input.value;
          if (!input.checkValidity() || (n.type === 'number' && (!input.value.trim() || !Number.isFinite(value)))) throw new Error('Enter a valid value');
        } catch (err) { status.textContent = err.message; return; }
        save.disabled = true;
        api.post('/api/prompt-history/config', {path:n.path,was:n.value,value:value}).then(function (result) {
          n.value = result.value; status.textContent = result.say;
        }).catch(function (err) { status.textContent = err.message; }).finally(function () { save.disabled = false; });
      });
      editor.appendChild(save); editor.appendChild(status); input.focus();
    }
    function sourceEditor(text) {
      sourceDraft = text; editor.replaceChildren(); editor.appendChild(make('h3', '', 'Future prompt source'));
      selectSource.replaceChildren();
      nodes.filter(function (n) { return n.type === 'text'; }).forEach(function (n) {
        var o = make('option', '', n.label); o.value = JSON.stringify(n.path); selectSource.appendChild(o);
      });
      editor.appendChild(selectSource);
      var choose = make('button', '', 'Open draft'); choose.type = 'button';
      choose.addEventListener('click', function () { var n = nodes.find(function (node) { return JSON.stringify(node.path) === selectSource.value; }); if (n) edit(n, sourceDraft); });
      editor.appendChild(choose); selectSource.focus();
    }
    function requestRow(row) {
      var d = make('details', 'ph-call'), summary = make('summary');
      summary.appendChild(make('b', '', row.model + ' / ' + row.purpose));
      summary.appendChild(make('time', '', new Date(row.at * 1000).toLocaleString() + ' / ' + row.state));
      summary.appendChild(make('span', '', row.preview)); d.appendChild(summary);
      d.addEventListener('toggle', function () {
        if (!d.open || d.dataset.loaded) return; d.dataset.loaded = 'yes';
        var body = make('div', 'ph-call-body'); d.appendChild(body); body.textContent = 'Loading request...';
        api.get('/api/prompt-history/' + encodeURIComponent(row.id)).then(function (got) {
          body.replaceChildren();
          var request = got.request || {}, messages = request.messages || [{role:'prompt',content:request.prompt || ''}];
          if (request.system) messages = [{role:'system',content:request.system}].concat(messages);
          messages.forEach(function (m) {
            var message = detail(body, m.role || 'message', m.content || m, m.role === 'system');
            if (typeof m.content === 'string') {
              var revise = make('button', '', 'Edit future source'); revise.type = 'button';
              revise.addEventListener('click', function () { sourceEditor(m.content); }); message.appendChild(revise);
            }
          });
          detail(body, 'Sampling and request options', Object.assign({},request,{messages:undefined,prompt:undefined,system:undefined}));
          detail(body, 'Output / conversation', got.response, true);
          detail(body, 'Properties observed at dispatch', got.properties);
          body.appendChild(make('p', 'ph-notice', got.properties_evidence));
          if (got.error) body.appendChild(make('p', 'ph-notice', got.error));
        }).catch(function (err) { body.textContent = err.message; delete d.dataset.loaded; });
      }); return d;
    }
    function load() {
      if (loading) return; loading = true; more.disabled = true; var current = epoch;
      api.get('/api/prompt-history?limit=30&before=' + before + '&model=' + encodeURIComponent(models.value)).then(function (got) {
        if (current !== epoch || !panel.isConnected) return;
        notice.textContent = got.capture_error || got.coverage;
        var selected = models.value; models.replaceChildren(); var all = make('option', '', 'All models'); all.value = ''; models.appendChild(all);
        (got.models || []).forEach(function (model) { models.appendChild(make('option', '', model)); }); models.value = selected;
        (got.rows || []).forEach(function (row) { list.appendChild(requestRow(row)); });
        before = got.next || 0; more.hidden = !before || !graph.hidden;
        if (!list.childElementCount) notice.textContent += ' No requests recorded yet.';
      }).catch(function (err) { if (current === epoch) notice.textContent = err.message; })
        .finally(function () { if (current === epoch) { loading = false; more.disabled = false; } });
    }
    function config() {
      api.get('/api/prompt-history/config').then(function (got) {
        nodes = got.nodes || []; group.replaceChildren(); var all = make('option', '', 'All properties'); all.value = ''; group.appendChild(all);
        Array.from(new Set(nodes.map(function (n) { return n.group; }))).forEach(function (name) { group.appendChild(make('option', '', name)); });
        graph.replaceChildren(); (got.roles || []).forEach(function (role) {
          var node = make('section', 'ph-node'); node.appendChild(make('h3','',role.name));
          node.appendChild(make('p','', (role.systems || []).join(', ')));
          nodes.filter(function (n) { return n.path.includes(role.id) || n.path.join('.').includes(role.id + '_') || n.path[1] === (role.id === 'host' ? 'persona' : role.id + '_persona'); }).forEach(function (n) {
            var b = make('button', '', n.label); b.type = 'button'; b.addEventListener('click', function () { edit(n); }); node.appendChild(b);
          }); graph.appendChild(node);
        }); propertyList();
      }).catch(function (err) { editor.textContent = err.message; });
    }
    function reset() { epoch++; before = 0; loading = false; list.replaceChildren(); load(); config(); }
    panel.reload = reset; return panel;
  }
  root.PinePromptHistory = {toggle: function (host, trigger) {
    var panel = host.querySelector('.ph-panel') || mount(host);
    panel.hidden = !panel.hidden; host.classList.toggle('ph-active', !panel.hidden);
    trigger.setAttribute('aria-pressed', String(!panel.hidden));
    if (!panel.hidden) panel.reload();
  }};
}(window));
