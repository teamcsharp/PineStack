(function (root) {
  'use strict';
  if (root.PineSupercutReview) return;
  var doc = root.document;
  function make(tag, cls, text) {
    var node = doc.createElement(tag); if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text); return node;
  }
  function readStored(key, fallback) {
    try { var value = root.localStorage.getItem(key); return value === null ? fallback : JSON.parse(value); }
    catch (e) { return fallback; }
  }
  function store(key, value) { try { root.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* session still works */ } }
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
  function url(path) {
    if (root.desktopMusicUrl) return root.desktopMusicUrl(path);
    if (/^https?:\/\//.test(path)) return path;
    return (root.PINE_BASE || (/^https?:/.test(root.location.protocol) ? '' : 'http://10.89.1.246:8096')) + path;
  }
  function button(host, label, action, cls) {
    var b = make('button', cls || 'psc-button', label); b.type = 'button';
    b.addEventListener('click', function () { action(b); }); host.appendChild(b); return b;
  }
  function field(host, label, kind, rows) {
    var lab = make('label', 'psc-field'), title = make('span', '', label), input = make(kind || 'input');
    input.setAttribute('aria-label', label); if (rows) input.rows = rows; lab.append(title, input); host.appendChild(lab); return input;
  }
  function section(host, title, open) {
    var details = make('details', 'psc-section'); details.open = !!open;
    details.appendChild(make('summary', '', title)); var body = make('div', 'psc-section-body'); details.appendChild(body); host.appendChild(details); return body;
  }
  function options(select, rows, empty) {
    var selected = select.value; select.replaceChildren();
    if (empty) { var blank = make('option', '', empty); blank.value = ''; select.appendChild(blank); }
    rows.forEach(function (row) { var op = make('option', '', row.name || row.title || row.product || row.id); op.value = row.id; select.appendChild(op); });
    if (Array.from(select.options).some(function (op) { return op.value === selected; })) select.value = selected;
  }
  function stop(audio) { if (!audio) return; try { audio.pause(); audio.removeAttribute('src'); audio.load(); } catch (e) { /* already disposed */ } }
  function displayStatus(row) {
    var text = String(row.status || 'waiting');
    if (row.total_words) text += ' · ' + Number(row.matched_words || 0) + ' / ' + Number(row.total_words) + ' words found';
    return text + (row.why ? ' · ' + row.why : '');
  }
  function mount(host, initial, callbacks) {
    callbacks = callbacks || {}; var dead = false, active = true, busy = false, selected = null, audio = null, pollTimer = 0, archiveOffset = 0;
    var customRows = [], archives = [], campaigns = [], templates = [], chosenTemplate = null, presetRows = [], h3Rows = [];
    var panel = make('section', 'pav-supercut-panel psc-panel'); panel.setAttribute('aria-label', 'Supercut studio'); host.appendChild(panel);
    var intro = make('div', 'psc-intro'); intro.append(make('b', '', 'Supercut studio'), make('p', '', 'Tell the SFX guy what to say. He finds, trims and joins existing audio, including H3 clips.'));
    panel.appendChild(intro);
    var note = make('p', 'psc-status', 'Loading the studio…'); note.setAttribute('role', 'status'); panel.appendChild(note);
    function say(text) { if (!dead) note.textContent = String(text || ''); }
    function run(b, fn) {
      b.disabled = true; return Promise.resolve().then(fn).then(function (got) {
        if (got && got.ok === false) throw new Error(got.why || got.detail || 'The station could not complete this action.'); return got;
      }).catch(function (e) { say(e.message || e); }).finally(function () { if (!dead) b.disabled = false; });
    }
    var editor = section(panel, 'Make a custom supercut', true);
    var promptBar = make('div', 'psc-row'); editor.appendChild(promptBar);
    var savedPrompt = make('select'); savedPrompt.setAttribute('aria-label', 'Saved supercut prompts'); promptBar.appendChild(savedPrompt);
    var promptName = field(editor, 'Prompt name', 'input'); promptName.placeholder = 'Name this supercut direction';
    var product = field(editor, 'Product or sponsor', 'input'); product.placeholder = 'What is this spot selling?';
    var words = field(editor, 'Words you want to hear', 'textarea', 4); words.placeholder = 'The exact words the SFX guy should assemble from existing clips';
    var explanation = field(editor, 'Tell the SFX guy how to cut it', 'textarea', 3); explanation.placeholder = 'Describe the rhythm, mood, pacing, surprises and stinger';
    var length = field(editor, 'Maximum length (seconds)', 'input'); length.type = 'number'; length.min = '30'; length.max = '60'; length.step = '1'; length.value = '45';
    editor.appendChild(make('p', 'psc-hint', 'Custom cuts can be shorter than this limit. Missing words are shown; source audio stays the source of the voice.'));
    var editActions = make('div', 'psc-actions'); editor.appendChild(editActions);
    function recallPrompt(row) {
      if (!row) return; product.value = row.product || ''; words.value = row.words || row.generated_script || row.script || row.recorded_text || '';
      explanation.value = row.explanation || row.prompt || ''; length.value = row.target_seconds || '45'; promptName.value = row.name || row.product || '';
    }
    function draft() { return {name: promptName.value.trim(), product: product.value.trim(), words: words.value.trim(), explanation: explanation.value.trim(), target_seconds: Number(length.value) || 45}; }
    savedPrompt.addEventListener('change', function () { recallPrompt(presetRows.find(function (row) { return row.id === savedPrompt.value; })); });
    button(editActions, 'Save prompt', function (b) { run(b, function () {
      var data = draft(); if (!data.name || !data.words) throw new Error('Name the prompt and enter the words to save.'); data.id = savedPrompt.value || undefined;
      return post('/api/sfx/supercut/presets', data).then(function () { say('Saved this supercut prompt.'); return loadPresets(); });
    }); });
    button(editActions, 'Save as new', function (b) { run(b, function () {
      var data = draft(); if (!data.name || !data.words) throw new Error('Name the prompt and enter the words to save.');
      return post('/api/sfx/supercut/presets', data).then(function () { say('Saved a new supercut prompt.'); return loadPresets(); });
    }); });
    button(editActions, 'Generate supercut', function (b) { run(b, function () {
      var data = draft(); if (!data.words) throw new Error('Enter the words the SFX guy should say.');
      if (!(data.target_seconds >= 30 && data.target_seconds <= 60)) throw new Error('Choose a maximum length from 30 to 60 seconds.');
      say('The SFX guy is finding and trimming source clips…');
      return post('/api/sfx/supercut/custom', data).then(function (job) { selected = job; showJob(job); return refreshJobs(); });
    }); }, 'psc-button primary');
    var result = section(panel, 'Selected supercut', true); var resultBody = make('div', 'psc-result'); result.appendChild(resultBody);
    function showJob(row) {
      selected = row; stop(audio); audio = null; resultBody.replaceChildren();
      resultBody.append(make('b', '', row.product || row.title || 'Custom supercut'), make('p', 'psc-hint', displayStatus(row)));
      if (row.words || row.script) resultBody.appendChild(make('pre', 'psc-script', row.words || row.script));
      var missing = (row.missing_words || []).concat(row.missing_phrases || []);
      if (missing.length) resultBody.appendChild(make('p', 'psc-missing', 'Still needed: ' + missing.join(' · ')));
      if (row.error) resultBody.appendChild(make('p', 'psc-missing', row.error));
      var acts = make('div', 'psc-actions'); resultBody.appendChild(acts);
      button(acts, 'Use these words', function () { recallPrompt(row); say('Recalled this direction in the custom editor.'); });
      if (row.id && /^scc-/.test(row.id) && /incomplete|error/.test(row.status || '')) button(acts, 'Retry missing words', function (b) { run(b, function () {
        return post('/api/sfx/supercut/custom/' + encodeURIComponent(row.id) + '/retry', {}).then(function (job) { showJob(job); return refreshJobs(); });
      }); });
      if (row.archive) showArchive(row.archive);
      else if (row.archive_id) loadArchive(row.archive_id);
      var cuts = row.cues || row.cuts || (row.plan && row.plan.clips) || [];
      if (cuts.length) showCuts(resultBody, cuts);
    }
    function showCuts(parent, cuts) {
      var proof = section(parent, 'Source cuts and trims', false); var list = make('ol', 'psc-cuts');
      cuts.forEach(function (cut) { list.appendChild(make('li', '', (cut.said || cut.word || cut.transcript || cut.name || cut.sid || 'Source clip')
        + ' · ' + Number(cut.from_s || cut.start || 0).toFixed(2) + '–' + Number(cut.until_s || cut.end || 0).toFixed(2) + 's'
        + (cut.source_generation ? ' · H3 ' + cut.source_generation : ''))); }); proof.appendChild(list);
    }
    function showArchive(row) {
      if (dead) return; selected = row; stop(audio); resultBody.replaceChildren();
      resultBody.append(make('b', '', row.title || row.product || 'Supercut'), make('p', 'psc-hint', Number(row.seconds || 0).toFixed(1) + ' seconds · ' + (row.cues || []).length + ' source cuts · Saved in SFX ads'));
      audio = make(row.video_url ? 'video' : 'audio', 'psc-audio'); audio.controls = true; audio.preload = 'none'; audio.autoplay = false;
      audio.src = url(row.video_url || row.audio_url || '/api/sfx/supercut/archive/' + encodeURIComponent(row.id) + '/audio'); resultBody.appendChild(audio);
      if (row.generated_script) { resultBody.append(make('b', '', 'Written script'), make('pre', 'psc-script', row.generated_script)); }
      if (row.recorded_text) { resultBody.append(make('b', '', 'Actual source audio'), make('pre', 'psc-script', row.recorded_text)); }
      var acts = make('div', 'psc-actions'); resultBody.appendChild(acts);
      button(acts, 'Use script in a new cut', function () { recallPrompt(row); say('The script is ready to edit for a new supercut.'); });
      button(acts, 'Add to reusable ads', function (b) { run(b, function () { return post('/api/sfx/supercut/archive/' + encodeURIComponent(row.id) + '/reuse', {})
        .then(function () { say('Added this exact supercut to the reusable ad library.'); }); }); });
      button(acts, 'Send to H3', function () { h3Block.parentNode.open = true; h3Block.scrollIntoView({block: 'nearest'}); say('Choose a visual prompt below, then generate the H3 video.'); });
      showCuts(resultBody, row.cues || []);
    }
    function loadArchive(id) {
      return get('/api/sfx/supercut/archive/' + encodeURIComponent(id)).then(function (row) { if (!dead) showArchive(row); }).catch(function (e) { say(e.message); });
    }
    var h3Block = section(panel, 'Render this supercut through H3', false);
    var h3Pick = make('select'); h3Pick.setAttribute('aria-label', 'H3 prompt history or preset'); h3Block.appendChild(h3Pick);
    var h3Direction = field(h3Block, 'Special H3 prompt', 'textarea', 4); h3Direction.placeholder = 'Describe the scene and action to accompany this supercut audio';
    h3Block.appendChild(make('p', 'psc-hint', 'The selected finished supercut supplies the audio reference. You can reuse a saved H3 prompt or a previous render’s direction.'));
    h3Pick.addEventListener('change', function () {
      var row = h3Rows.find(function (one) { return one.id === h3Pick.value; }); if (row) h3Direction.value = row.prompt || row.goal || row.direction || '';
    });
    var h3Actions = make('div', 'psc-actions'); h3Block.appendChild(h3Actions);
    button(h3Actions, 'Generate H3 video', function (b) { run(b, function () {
      if (!selected || !/^sca-/.test(selected.id || selected.archive_id || '')) throw new Error('Choose a finished supercut from the archive first.');
      var chosen = h3Rows.find(function (one) { return one.id === h3Pick.value; }) || {};
      var prompt = h3Direction.value.trim(); if (!prompt) throw new Error('Enter the scene or choose an H3 prompt.');
      return post('/api/sfx/supercut/archive/' + encodeURIComponent(selected.archive_id || selected.id) + '/h3', {prompt: prompt, preset_id: chosen.preset_id || '', from_prompt_id: chosen.prompt_id || '', air_it: false})
        .then(function (got) { if (!got || !(got.prompt_id || got.queue_id)) throw new Error('No H3 job was confirmed.'); say('H3 video queued. Its result will appear under H3 / Comfy renders.'); });
    }); }, 'psc-button primary');
    button(h3Actions, 'H3 / Comfy renders', function () { if (callbacks.selectTab) callbacks.selectTab('h3'); else if (root.PineAdViewer) root.PineAdViewer.selectTab('h3'); });

    var history = section(panel, 'Custom cuts and prompt history', false), historyList = make('div', 'psc-list'); history.appendChild(historyList);
    function refreshJobs() {
      return get('/api/sfx/supercut/custom?limit=40').then(function (got) {
        if (dead) return; customRows = got.rows || []; historyList.replaceChildren();
        if (!customRows.length) historyList.appendChild(make('p', 'psc-hint', 'Your custom supercuts will be kept here.'));
        customRows.forEach(function (row) { var item = make('div', 'psc-history-item'); item.appendChild(make('span', '', (row.product || 'Custom supercut') + ' · ' + displayStatus(row)));
          button(item, 'Review', function () { showJob(row); }); button(item, 'Recall prompt', function () { recallPrompt(row); say('Recalled the words and SFX direction.'); }); historyList.appendChild(item); });
        if (selected && /^scc-/.test(selected.id || '')) { var updated = customRows.find(function (r) { return r.id === selected.id; }); if (updated && JSON.stringify(updated) !== JSON.stringify(selected)) showJob(updated); }
      });
    }
    var library = section(panel, 'SFX ads archive', true); var libraryBar = make('div', 'psc-row'); library.appendChild(libraryBar);
    var search = make('input'); search.type = 'search'; search.placeholder = 'Search supercuts and products'; search.setAttribute('aria-label', 'Search supercut archive'); libraryBar.appendChild(search);
    button(libraryBar, 'Refresh', function (b) { run(b, function () { archiveOffset = 0; return loadLibrary(); }); });
    var archiveList = make('div', 'psc-archive-list'); library.appendChild(archiveList);
    var paging = make('div', 'psc-actions'); library.appendChild(paging);
    var prev = button(paging, 'Previous', function (b) { run(b, function () { archiveOffset = Math.max(0, archiveOffset - 24); return loadLibrary(); }); });
    var next = button(paging, 'Next', function (b) { run(b, function () { archiveOffset += 24; return loadLibrary(); }); });
    var count = make('span', 'psc-hint'); paging.appendChild(count);
    search.addEventListener('change', function () { archiveOffset = 0; loadLibrary().catch(function (e) { say(e.message); }); });
    function loadLibrary() {
      return get('/api/sfx/supercut/archive?summary=true&limit=24&offset=' + archiveOffset + '&q=' + encodeURIComponent(search.value.trim())).then(function (got) {
        if (dead) return; archives = got.rows || []; archiveList.replaceChildren(); prev.disabled = archiveOffset === 0; next.disabled = !got.has_more;
        count.textContent = String(got.total || 0) + ' saved supercuts';
        if (!archives.length) archiveList.appendChild(make('p', 'psc-hint', 'Finished supercuts are saved here for review and reuse.'));
        archives.forEach(function (row) { var tile = make('button', 'psc-archive-tile'); tile.type = 'button';
          tile.append(make('b', '', row.product || row.title || 'Supercut'), make('span', '', Number(row.seconds || 0).toFixed(1) + 's · ' + new Date(Number(row.created_at || 0) * 1000).toLocaleString()));
          tile.addEventListener('click', function () { loadArchive(row.id); }); archiveList.appendChild(tile); });
      });
    }
    var hourlies = section(panel, 'Hourly product campaigns', true); var popupLabel = make('label', 'psc-check'), popup = make('input'); popup.type = 'checkbox'; popup.checked = noticesEnabled();
    popup.setAttribute('aria-label', 'Show new hourly supercut popups'); popupLabel.append(popup, make('span', '', 'Show new hourly scripts and finished cuts in a popup')); hourlies.appendChild(popupLabel);
    popup.addEventListener('change', function () { store('pineSupercutHourlyPopups', popup.checked); if (!popup.checked) closeNotice(); });
    var hourList = make('div', 'psc-list'); hourlies.appendChild(hourList);
    function loadCampaigns() {
      return get('/api/sfx/supercut/campaigns?limit=24').then(function (got) {
        if (dead) return; campaigns = got.items || got.rows || []; hourList.replaceChildren();
        campaigns.forEach(function (row) { var item = make('div', 'psc-history-item');
          var stamp = row.hour_epoch ? new Date(row.hour_epoch * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : row.hour;
          item.appendChild(make('span', '', stamp + ' · ' + (row.product || 'Selecting a product') + ' · ' + row.status));
          button(item, 'Script / review', function () { showJob(row); }); if (row.script) button(item, 'Use script', function () { recallPrompt(row); }); hourList.appendChild(item); });
        if (!campaigns.length) hourList.appendChild(make('p', 'psc-hint', 'A fresh product script is written each hour.'));
      });
    }
    var productsBlock = section(panel, 'Products to sell', false); var productMode = field(productsBlock, 'Hourly product selection', 'select');
    [['mixed', 'Invented products + my saved list'], ['saved', 'My saved products'], ['invented', 'Invented products'], ['fixed', 'Fixed product']].forEach(function (one) { var op = make('option', '', one[1]); op.value = one[0]; productMode.appendChild(op); });
    var productList = field(productsBlock, 'Saved products — one per line: name | description', 'textarea', 5);
    var campaignOnLabel = make('label', 'psc-check'), campaignOn = make('input'); campaignOn.type = 'checkbox'; campaignOnLabel.append(campaignOn, make('span', '', 'Generate an hourly product campaign')); productsBlock.appendChild(campaignOnLabel);
    button(productsBlock, 'Save products', function (b) { run(b, function () {
      var rows = productList.value.split(/\r?\n/).filter(function (line) { return line.trim(); }).map(function (line) { var parts = line.split('|'); return {name: parts.shift().trim(), description: parts.join('|').trim()}; });
      return request('PUT', '/api/sfx/supercut/products', {product_mode: productMode.value, products: rows, campaign_enabled: campaignOn.checked})
        .then(function () { say('Saved the product selection for upcoming hourly campaigns.'); });
    }); });
    function loadProducts() { return get('/api/sfx/supercut/products').then(function (got) { if (dead) return;
      productMode.value = got.product_mode || 'mixed'; campaignOn.checked = got.enabled !== false && got.campaign_enabled !== false;
      productList.value = (got.products || []).map(function (row) { return typeof row === 'string' ? row : row.name + (row.description ? ' | ' + row.description : ''); }).join('\n');
    }); }
    var templateBlock = section(panel, 'Hourly system and generation prompts', false); var templatePick = field(templateBlock, 'Saved hourly template', 'select');
    var templateName = field(templateBlock, 'Template name', 'input'), templateSystem = field(templateBlock, 'System prompt', 'textarea', 5), templateGeneration = field(templateBlock, 'Generation prompt', 'textarea', 5);
    var templateMode = field(templateBlock, 'Template roulette', 'select'); [['fixed','Use selected template'],['cycle','Cycle templates'],['random','Weighted random']].forEach(function (one) { var op = make('option','',one[1]); op.value = one[0]; templateMode.appendChild(op); });
    var templateActions = make('div', 'psc-actions'); templateBlock.appendChild(templateActions);
    function recallTemplate(id) { chosenTemplate = templates.find(function (row) { return row.id === id; }) || templates[0]; if (!chosenTemplate) return;
      templatePick.value = chosenTemplate.id; templateName.value = chosenTemplate.name; templateSystem.value = chosenTemplate.text || ''; templateGeneration.value = chosenTemplate.generation_prompt || ''; }
    templatePick.addEventListener('change', function () { recallTemplate(templatePick.value); });
    function saveTemplate(fresh) {
      if (!chosenTemplate) throw new Error('Wait for the hourly templates to load.');
      if (!templateName.value.trim() || !templateSystem.value.trim() || !templateGeneration.value.trim()) throw new Error('Name the template and enter both prompts.');
      var payload = Object.assign({}, chosenTemplate, {name: templateName.value.trim(), text: templateSystem.value, generation_prompt: templateGeneration.value}); if (fresh) delete payload.id;
      return post('/api/segment/prompts/sfx_supercut/alternative', payload).then(function (got) { say('Saved the hourly prompt template.'); return loadTemplates(got.alternative && got.alternative.id); });
    }
    button(templateActions, 'Save template', function (b) { run(b, function () { return saveTemplate(false); }); });
    button(templateActions, 'Save as new', function (b) { run(b, function () { return saveTemplate(true); }); });
    button(templateActions, 'Use / cycle / randomize', function (b) { run(b, function () { if (!chosenTemplate) throw new Error('Choose a saved template.');
      return post('/api/segment/prompts/sfx_supercut/mode', {mode: templateMode.value === 'fixed' ? 'fixed:' + chosenTemplate.id : templateMode.value}).then(function () { say('Updated the template selection for upcoming hours.'); });
    }); });
    function loadTemplates(id) { return get('/api/dynamic-segments').then(function (got) { if (dead) return;
      var data = (got.kinds || {}).sfx_supercut || {}; templates = data.alternatives || []; options(templatePick, templates);
      templateMode.value = data.mode === 'cycle' || data.mode === 'random' ? data.mode : 'fixed'; recallTemplate(id || (data.mode || '').replace(/^fixed:/, '') || templatePick.value);
    }); }
    function loadPresets() { return get('/api/sfx/supercut/presets').then(function (got) { if (dead) return; presetRows = got.presets || got.rows || []; options(savedPrompt, presetRows, 'New custom prompt'); }); }
    function loadH3() { return Promise.all([get('/api/h3/prompts'), get('/api/h3/prompts/history?limit=24')]).then(function (results) {
      if (dead) return; h3Rows = (results[0].presets || []).map(function (p) { return {id: 'preset:' + p.id, preset_id: p.id, name: 'Preset · ' + p.name, prompt: p.goal || p.clip || p.host || ''}; });
      (results[1].hours || []).forEach(function (h, i) { var words = h.preset || h.words || {}; h3Rows.push({id: 'history:' + (h.hour || i), name: 'History · ' + (h.hour || '') + ' · ' + (words.name || h.name || 'H3'), prompt: words.goal || h.goal || h.brief || h.direction || '', prompt_id: ((h.videos || [])[0] || {}).prompt_id || ''}); });
      options(h3Pick, h3Rows, 'Choose a preset or previous H3 prompt');
    }); }
    function tick() {
      if (dead || !active || doc.hidden || busy) return; busy = true;
      Promise.allSettled([refreshJobs(), loadCampaigns(), loadLibrary()]).then(function (results) {
        if (!dead) { var errors = results.filter(function (r) { return r.status === 'rejected'; }); if (errors.length) say('Some studio information could not be refreshed: ' + errors[0].reason.message); }
      }).finally(function () { busy = false; });
    }
    Promise.allSettled([refreshJobs(), loadLibrary(), loadCampaigns(), loadProducts(), loadTemplates(), loadPresets(), loadH3()]).then(function (results) {
      if (dead) return; var errors = results.filter(function (r) { return r.status === 'rejected'; }); say(errors.length ? 'Some studio information is unavailable: ' + errors[0].reason.message : 'Ready. Select a saved cut or make a custom supercut.');
      if (initial) { if (initial.archive_id || /^sca-/.test(initial.id || '')) loadArchive(initial.archive_id || initial.id); else if (initial.id) get('/api/sfx/supercut/campaigns/' + encodeURIComponent(initial.id)).then(showJob).catch(function (e) { say(e.message); }); else recallPrompt(initial); }
    });
    pollTimer = root.setInterval(tick, 5000);
    return {panel: panel, select: function (row) { if (row.archive_id || /^sca-/.test(row.id || '')) return loadArchive(row.archive_id || row.id); showJob(row); },
      setActive: function (on) { active = !!on; if (!active) { if (audio) audio.pause(); } else tick(); },
      dispose: function () { dead = true; root.clearInterval(pollTimer); stop(audio); panel.remove(); }};
  }
  var seen = readStored('pineSupercutSeen', {}), initialized = false, notice = null, noticeRow = null, noticePolling = false;
  function noticesEnabled() { return readStored('pineSupercutHourlyPopups', true) !== false; }
  function closeNotice() { if (notice) notice.remove(); notice = null; noticeRow = null; }
  function revision(row) { return [row.id, row.generated_at || '', row.script || '', row.archive_id || '', row.status || ''].join('|'); }
  function noticeReady(row) { return !!(row && row.id && (row.script || row.archive_id || row.archive)); }
  function announce(row) {
    var rev = revision(row); if (seen[row.id] === rev) return false; seen[row.id] = rev;
    var keys = Object.keys(seen); if (keys.length > 150) keys.slice(0, keys.length - 150).forEach(function (id) { delete seen[id]; }); store('pineSupercutSeen', seen);
    if (!noticesEnabled()) return false;
    if (notice && noticeRow && noticeRow.id === row.id) { notice.querySelector('.psc-hourly-script').textContent = row.script || 'The finished cut is ready.'; noticeRow = row; return true; }
    closeNotice(); noticeRow = row; notice = make('section', 'psc-hourly'); notice.setAttribute('role', 'region'); notice.setAttribute('aria-label', 'New hourly supercut');
    var head = make('div', 'psc-row'); head.appendChild(make('b', '', 'Hourly Super Cut · ' + (row.product || 'Pine Box FM'))); button(head, '×', closeNotice, 'psc-notice-close'); notice.appendChild(head);
    notice.appendChild(make('pre', 'psc-hourly-script', row.script || 'The finished source clip is ready.'));
    button(notice, 'Review / customize', function () { var chosen = noticeRow; closeNotice(); open(chosen); }, 'psc-button primary');
    doc.body.appendChild(notice); return true;
  }
  function observe(rows) {
    rows = (rows || []).filter(noticeReady).slice().sort(function (a, b) { return Number(a.created_at || 0) - Number(b.created_at || 0); });
    if (!initialized) { rows.forEach(function (row) { seen[row.id] = revision(row); }); initialized = true; store('pineSupercutSeen', seen); return; }
    var fresh = rows.filter(function (row) { return seen[row.id] !== revision(row) && (seen[row.id] || Number(row.created_at || row.generated_at || 0) >= bootAt - 5); });
    if (fresh.length) announce(fresh[fresh.length - 1]);
  }
  function open(initial) {
    if (doc.body.classList.contains('pine-pip') && !root.PINE_NATIVE_TOOLS && root.pineDesktop && root.pineDesktop.pipToolsOpen) {
      return root.pineDesktop.pipToolsOpen({supercut: initial || {}, tab: 'supercut'});
    }
    if (root.PineAdViewer && root.PineAdViewer.openSupercuts) return root.PineAdViewer.openSupercuts(initial || null);
  }
  var bootAt = Date.now() / 1000;
  function pollNotices() {
    if (noticePolling || doc.hidden || !root.pineDesktop && !root.PINE_BASE && !/^https?:/.test(root.location.protocol)) return;
    noticePolling = true; get('/api/sfx/supercut/campaigns?limit=8').then(function (got) { observe(got.items || got.rows || []); }).catch(function () { /* resume after reconnect */ }).finally(function () { noticePolling = false; });
  }
  root.PineSupercutReview = {mount: mount, open: open, closeNotice: closeNotice, observe: observe, announce: announce, revision: revision, noticesEnabled: noticesEnabled};
  if (doc && !root.PINE_NATIVE_TOOLS) { root.setTimeout(pollNotices, 8000); root.setInterval(pollNotices, 12000); }
}(typeof window !== 'undefined' ? window : globalThis));
