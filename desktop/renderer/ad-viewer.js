(function (root) {
  'use strict';
  var opened = null;
  function make(tag, cls, text) {
    var n = document.createElement(tag); n.className = cls || '';
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function command(label, icon, action) {
    var n = make('button', 'pav-icon'); n.type = 'button';
    n.title = label; n.setAttribute('aria-label', label);
    if (root.pineIcon) n.innerHTML = root.pineIcon(icon);
    else { n.setAttribute('data-icon', icon); n.textContent = label; }
    n.addEventListener('click', action); return n;
  }
  function mediaFile(row) {
    var files = (row && row.files || []).filter(function (f) { return typeof f === 'string'; });
    return files.find(function (f) { return /\.(mp4|webm|mov|m4v)$/i.test(f); })
      || files.find(function (f) { return /\.(png|jpe?g|webp|gif)$/i.test(f); }) || '';
  }
  /* [h3-prompts] The words a video was told, as the gallery shows them under
     it: the preset, how the hour came by it, the road and each prompt - from
     the row's own record (h3_prompts), or, for a video made before that
     record, what the row kept (the direction it was sent, its line, the final
     H3 prompt). Pure: the popup paints it, the tests read it. */
  var USED_ROADS = {clip: 'clip road - a dialogue clip was the reference',
    gallery: 'gallery road - a gallery picture was the reference', host: 'host road - the host\'s LoRA presented'};
  function usedHow(rec) {
    var roll = rec && rec.roll && typeof rec.roll === 'object' ? rec.roll : {};
    if (!rec) return '';
    if (rec.how === 'next') return 'pinned for the hour';
    if (rec.how === 'dice') {
      if (roll.by === 'system3') return 'rolled by System 3: d100 ' + roll.dice + ', ' + roll.index + ' of ' + roll.of;
      if (roll.by === 'station') return 'rolled by the station (System 3 off): ' + roll.index + ' of ' + roll.of;
      return 'dice on, ' + (roll.why || 'no roll');
    }
    return 'the active preset';
  }
  function usedRolls(rolls) {
    /* [s3-visuals] the hourly door's own dice (h3.hourly_source / _fresh /
       _marker / _host), recorded with the hour and carried on the row's
       h3_prompts record - worded only when a roll was actually made
       (never fake dice; an empty record stays silent). */
    if (!rolls || typeof rolls !== 'object') return '';
    var bits = [];
    function one(name, rec) {
      if (!rec || typeof rec !== 'object' || rec.dice == null) return;
      if (rec.kind === 'chance') {
        bits.push(name + ': ' + (rec.hit ? 'yes' : 'no') + ' (d100 ' + rec.dice
          + ' against ' + Math.round((rec.odds || 0) * 100) + '%)');
      } else if (rec.index != null && rec.of != null) {
        bits.push(name + ': ' + String(rec.picked || rec.label || '') + ' (d100 ' + rec.dice
          + ', ' + rec.index + ' of ' + rec.of + ')');
      } else {
        bits.push(name + ': d100 ' + rec.dice);
      }
    }
    one('host', rolls.host); one('source', rolls.source);
    one('fresh pick', rolls.fresh); one('window marker', rolls.marker);
    /* [h3-speak] the H3SPEAK node: what kind of aired talk, which line, the
       Speakerbox document (no aired line passed), how many sentences, which ones */
    one('dialogue kind', rolls.speak_lean); one('line said on air', rolls.speak_line);
    one('speakerbox document', rolls.speak_doc); one('sentences to take', rolls.speak_count);
    one('sentences', rolls.speak_sentences); one('forced line', rolls.speak_forced);
    /* [h3-slot-roll] a {speakerbox} or {a|b|c} in the prompt: the document, the sentence, the option */
    one('{speakerbox} document', rolls.slot_doc); one('{speakerbox} sentence', rolls.slot_sentence);
    one('{choice}', rolls.slot_choice);
    return bits.join('  -  ');
  }
  /* [h3-slot-roll] "I want to see a rolodex roll for the doc and then the
     sentence used" (the operator): each slot roll the hour recorded with its
     options spins through them and stops on what landed, one after another. */
  function slotReels(rolls) {
    if (!rolls || typeof rolls !== 'object') return [];
    var out = [];
    [['slot_doc', '{speakerbox} - the document'], ['slot_sentence', '{speakerbox} - the sentence'],
     ['slot_choice', '{choice} - the option']].forEach(function (k) {
      var r = rolls[k[0]];
      if (!r || !r.picked || !Array.isArray(r.opts) || !r.opts.length) return;
      out.push({name: k[1], picked: String(r.picked), opts: r.opts.map(String), dice: r.dice,
        index: r.index, of: r.of});
    });
    return out;
  }
  /* [ad-roll] "When showing a Pine box ad that used the speaker box or the
     roulette system, show the roulette message box animated here ... It should
     look the same as the feed view. If i click on it, allow me to view the
     details" (the operator, 2026-09-30). Every roll the hour recorded, as the
     rows the feed's roll stage (PineRollTag) plays: the preset's roll, the
     door's own dice, the H3SPEAK node, and the {speakerbox}/{choice} slots.
     Only rolls actually made - an empty record gives no rows. Pure. */
  var ROLL_ROWS = [['host', 'host'], ['source', 'source'], ['fresh', 'fresh pick'], ['marker', 'window marker'],
    ['speak_lean', 'dialogue kind'], ['speak_line', 'line said on air'], ['speak_doc', 'speakerbox document'],
    ['speak_count', 'sentences to take'], ['speak_sentences', 'sentences'], ['speak_forced', 'forced line'],
    ['slot_doc', '{speakerbox} document'], ['slot_sentence', '{speakerbox} sentence'], ['slot_choice', '{choice}'],
    /* [h3-overview] the technical overview's own dice */
    ['ov_feature', 'feature presented'], ['ov_presenter', 'presenter'], ['ov_count', 'how many actions'],
    ['ov_action', 'actions'], ['ov_gallery', 'gallery picture carried'], ['ov_dialogue', 'DJ line on the billboard'],
    ['ov_system', 'system prompt']];
  function rollRow(table, r) {
    if (!r || typeof r !== 'object' || r.dice == null) return null;
    var main;
    if (r.kind === 'chance') {
      main = {dice: r.dice, opts: ['no', 'yes'], hit: r.hit ? 1 : 0, label: r.hit ? 'yes' : 'no', of: 2};
    } else if (r.picked == null && r.u != null) {
      /* a plain roll (where the window's markers land): the number itself */
      var at = 'lands at ' + Number(r.u).toFixed(2);
      main = {dice: r.dice, opts: [at], hit: 0, label: at, index: 1, of: 1, counted: true};
    } else if (!(Array.isArray(r.opts) && r.opts.length) && r.index != null && r.of != null) {
      /* only the landing was recorded, not the list: the reel counts through
         the positions (the feed's own counted reel) and names nothing it was not told */
      var named = String(r.picked != null ? r.picked : (r.label || ''));
      main = {dice: r.dice, opts: [named], hit: 0, label: named, index: Number(r.index) || 0,
        of: Number(r.of) || 0, counted: true};
    } else {
      var label = String(r.picked != null ? r.picked : (r.label != null ? r.label : ''));
      var opts = Array.isArray(r.opts) && r.opts.length ? r.opts.map(String) : [label];
      var hit = opts.indexOf(label);
      if (hit < 0 && r.index != null) hit = Math.min(opts.length - 1, Math.max(0, Number(r.index) - 1));
      if (hit < 0) { opts.push(label); hit = opts.length - 1; }
      main = {dice: r.dice, opts: opts, hit: hit, label: label, of: Number(r.of) || opts.length};
    }
    return {fam: 'H3', table: table, event: '', main: main};
  }
  function rollRows(rec) {
    if (!rec || typeof rec !== 'object') return [];
    var rows = [];
    if (rec.how === 'dice' && rec.roll && rec.roll.dice != null) {
      var preset = rollRow('the preset', Object.assign({}, rec.roll,
        {picked: rec.roll.picked || (rec.preset && rec.preset.name) || ''}));
      if (preset) rows.push(preset);
    }
    var rolls = rec.rolls && typeof rec.rolls === 'object' ? rec.rolls : {};
    ROLL_ROWS.forEach(function (k) { var r = rollRow(k[1], rolls[k[0]]); if (r) rows.push(r); });
    return rows;
  }
  function roloStyle() {
    if (document.getElementById('pavRoloStyle')) return;
    var st = document.createElement('style');
    st.id = 'pavRoloStyle';
    st.textContent = '.pav-rolo{display:flex;flex-direction:column;gap:10px;margin:4px 0 2px}'
      + '.pav-rolo-name{display:block;font-size:11.5px;color:#8ea0ad;margin-bottom:3px}'
      + '.pav-rolo-win{height:30px;overflow:hidden;border:1px solid #35505c;border-radius:6px;background:#081013;'
      + 'position:relative;box-shadow:inset 0 8px 8px -8px #000,inset 0 -8px 8px -8px #000}'
      + '.pav-rolo-card{height:30px;line-height:30px;padding:0 10px;white-space:nowrap;overflow:hidden;'
      + 'text-overflow:ellipsis;color:#b9c6ce;font-size:12.5px}'
      + '.pav-rolo-card.hit{color:#edf3f5;font-weight:600;background:rgba(101,199,218,.16)}'
      + '.pav-rolo-picked{margin:4px 0 0;font-size:12.5px;color:#edf3f5;opacity:0;transition:opacity .4s}'
      + '.pav-rolo-picked.on{opacity:1}';
    document.head.appendChild(st);
  }
  function rolodex(reels) {
    roloStyle();
    var box = make('div', 'pav-rolo'), H = 30, SPIN = 1600, GAP = 400;
    reels.forEach(function (r, n) {
      var row = make('div', 'pav-rolo-row');
      row.appendChild(make('span', 'pav-rolo-name', r.name + (r.dice != null ? ' - d100 ' + r.dice : '')
        + (r.index != null && r.of != null ? ', ' + r.index + ' of ' + r.of : '')));
      var opts = r.opts.slice(), at = opts.indexOf(r.picked);
      if (at < 0) { opts.push(r.picked); at = opts.length - 1; }
      var list = opts.length > 1 ? opts.concat(opts) : opts, land = opts.length > 1 ? opts.length + at : at;
      var win = make('div', 'pav-rolo-win'), strip = make('div', 'pav-rolo-strip');
      list.forEach(function (o, i) { strip.appendChild(make('div', 'pav-rolo-card' + (i === land ? ' hit' : ''), o)); });
      win.appendChild(strip);
      row.appendChild(win);
      var picked = make('p', 'pav-rolo-picked', r.picked);
      row.appendChild(picked);
      box.appendChild(row);
      root.setTimeout(function () {
        strip.style.transition = 'transform ' + SPIN + 'ms cubic-bezier(.12,.7,.18,1)';
        strip.style.transform = 'translateY(' + (-land * H) + 'px)';
        root.setTimeout(function () { picked.classList.add('on'); }, SPIN);
      }, 120 + n * (SPIN + GAP));
    });
    return box;
  }
  function usedSpeak(sp) {
    /* [h3-speak] the H3SPEAK node's record: rolled from a line a person was
       heard saying (who, when, the feeling System 3 rolled for it), from a
       Speakerbox document, or FORCED and why. */
    if (!sp || typeof sp !== 'object') return '';
    var took = sp.count && sp.count.took ? sp.count.took + ' of ' + (sp.count.rolled || sp.count.took)
      + ' sentence' + (sp.count.took === 1 ? '' : 's') : '';
    if (sp.verdict === 'forced') {
      return 'FORCED - ' + String(sp.forced_by || 'the forced line') + (sp.why ? ' (' + sp.why + ')' : '');
    }
    if (sp.source === 'speakerbox') {
      return 'rolled from the Speakerbox document ' + String(sp.doc || '?') + (took ? ': ' + took : '')
        + (sp.why ? ' - no aired line passed' : '');
    }
    var s = sp.said || {};
    var at = s.at ? new Date(Number(s.at) * 1000) : null;
    var when = at && !isNaN(at) ? ' at ' + String(at.getHours()).padStart(2, '0') + ':'
      + String(at.getMinutes()).padStart(2, '0') : '';
    var feel = s.emotion ? ', feeling ' + s.emotion + (s.intensity != null ? ' ' + Number(s.intensity).toFixed(2) : '') : '';
    return 'rolled from what ' + String(s.name || s.who || 'a voice') + ' said on air' + when
      + (s.round ? ' (' + s.round + (s.turns > 1 ? ', a monologue of ' + s.turns + ' turns' : '') + ')' : '')
      + feel + (took ? ': ' + took : '');
  }
  function usedWords(row) {
    row = row || {};
    var rec = row.h3_prompts && typeof row.h3_prompts === 'object' ? row.h3_prompts : null;
    var items = [];
    function add(label, text, key) {
      text = String(text == null ? '' : text).trim();
      if (text) items.push({label: label, text: text, key: key});
    }
    if (rec) {
      add('Brief', rec.goal, 'goal');
      add('Direction sent', rec.direction || row.request, 'direction');
      add('Line spoken', rec.speech || row.speech, 'speech');
      add('Style', rec.style, 'style');
      add('Audio direction', rec.audio_direction, 'audio_direction');
      add('Constraints', rec.constraints, 'constraints');
      add('Hourly rolls', usedRolls(rec.rolls), 'rolls');   /* [s3-visuals] the door's dice, when they rolled */
      var reels = slotReels(rec.rolls);                     /* [h3-slot-roll] the slots' rolodex */
      if (reels.length) items.push({label: 'Rolled slots', key: 'slots', reels: reels,
        text: reels.map(function (r) { return r.name + ': ' + r.picked; }).join('\n')});
      add('Dialogue (H3SPEAK)', usedSpeak(rec.speak), 'speak');   /* [h3-speak] where the words came from */
      add('Final H3 prompt', row.tags, 'tags');
      var name = rec.preset && rec.preset.name ? String(rec.preset.name) : 'a preset';
      return {recorded: true, hourly: true, preset: name, how: usedHow(rec), road: USED_ROADS[rec.road] || '',
        at: Number(rec.at) || 0, items: items, reusable: true, note: '',
        summary: '"' + name + '" - ' + usedHow(rec) + (rec.road ? ' - ' + rec.road + ' road' : '')};
    }
    add('Direction sent', row.request, 'direction');
    add('Line spoken', row.speech, 'speech');
    add('Final H3 prompt', row.tags, 'tags');
    var hourly = row.hourly === true || /The person or people on screen must Make a short, funny but professional Pine Box FM sponsor stinger/.test(String(row.request || ''));
    return {recorded: false, hourly: hourly, preset: '', how: '', road: '', at: 0, items: items,
      reusable: items.some(function (i) { return i.key === 'direction'; }),
      summary: !items.length ? 'not recorded' : hourly ? 'an hourly render from before its prompts were kept' : 'what it was sent',
      note: !items.length ? 'No prompt was recorded with this video.'
        : hourly ? 'An hourly render made before the prompts were kept with the video: this is what it was sent - its preset and the hour\'s brief were not recorded.' : ''};
  }
  function usedTime(at) {
    var d = new Date(Number(at || 0) * 1000);
    if (!at || isNaN(d.getTime())) return '--:--';
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function copyByHand(text) {
    var area = document.createElement('textarea'); area.value = text; area.setAttribute('readonly', '');
    area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area); area.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; } finally { area.remove(); }
    return ok ? Promise.resolve() : Promise.reject(new Error('copy refused'));
  }
  function copyWords(text) {
    text = String(text == null ? '' : text);
    try {
      /* the desk's window is file:// - navigator.clipboard is not there (#990) */
      if (root.pineDesktop && typeof root.pineDesktop.copyText === 'function' && root.pineDesktop.copyText(text) !== false) return Promise.resolve();
    } catch (e) { /* the page's own clipboard, below */ }
    if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { return copyByHand(text); });
    }
    return copyByHand(text);
  }
  function open(initial, gallery) {
    if (opened) opened();
    var veil = make('div', 'pine-voice-ad-popup'); veil.id = 'pineVoiceAdPopup';
    var box = make('section', 'pine-voice-ad-card');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', gallery ? 'Pine Box Gallery' : 'Pine Box generated ads');
    var head = make('header', 'pav-head'); head.appendChild(make('b', '', gallery ? 'Pine Box Gallery' : 'Your Pine Box ad is ready'));
    /* [ad-roll] the ad's roll, played in the header the way the feed plays a
       line's: the same stage, small. A tap opens how each roll landed. */
    var rollHead = make('div', 'pav-rollhead'); rollHead.hidden = true;
    rollHead.setAttribute('role', 'button'); rollHead.tabIndex = 0;
    rollHead.title = 'How the roulette rolled this ad - tap for the details';
    rollHead.setAttribute('aria-label', rollHead.title);
    head.appendChild(rollHead);
    var rollTag = null, rollRec = null;
    var position = make('span', 'pav-position'); head.appendChild(position);
    var rows = [], signatures = {}, index = 0, revision = 0, gone = false, references = {}, original = false, currentRow = '';
    var pendingRows = [], imageDrafts = {}, imageJobs = {}, splicePending = false;
    var cursor = '', loading = false, stripStart = 0, crawl = 0, pausedUntil = 0, loadFailed = false;
    var disposeMedia = function () {}, exportTimer = 0, h3Timer = 0, h3State = null, duckApi = null, h3Loading = false;
    var h3Bar = make('div', 'pav-h3');
    var h3Label = make('label', 'pav-h3-toggle');
    var h3Toggle = make('input'); h3Toggle.type = 'checkbox';
    h3Toggle.setAttribute('aria-label', 'Hourly H3 stingers');
    h3Label.appendChild(h3Toggle); h3Label.appendChild(make('span', '', 'H3'));
    var h3Meter = make('i', 'pav-h3-meter'); var h3Fill = make('b'); h3Meter.appendChild(h3Fill);
    var h3Time = make('output', 'pav-h3-time', '--:--');
    h3Bar.append(h3Label, h3Meter, h3Time);
    /* [h3-quality] "expose the quality settings for H3 in the pine box gallery
       when i click the settings": the gear beside the H3 toggle opens the
       profile - preset, steps, frame size, longest clip - with the box's heat
       and free memory beside it. Apply saves it to the station; every H3
       render from then on runs at it, stepped down while the box is hot or
       short of room (comfy_workshop.quality_for_box). */
    var qualityPanel = make('div', 'pav-quality'); qualityPanel.hidden = true;
    var h3Gear = command('H3 quality settings', 'c:settings', function () {
      /* [gear-works] "make sure this button works" (the operator, from the
         Hourly prompts screen): that screen hides everything but its own
         (.pav-on-prompts), so the panel opened unseen. The gear leaves the
         prompts first, then shows the panel where it can be seen. */
      if (pScreen && !pScreen.hidden) { showPrompts(false); qualityPanel.hidden = false; }
      else qualityPanel.hidden = !qualityPanel.hidden;
      h3Gear.setAttribute('aria-expanded', String(!qualityPanel.hidden));
      if (!qualityPanel.hidden) {
        paintQuality(h3State); loadH3();
        try { qualityPanel.scrollIntoView({block: 'nearest'}); } catch (e) { /* older engine */ }
      }
    });
    h3Bar.appendChild(h3Gear);
    /* [h3-prompts] "Put an option here of a P for prompt and whenever I click it
       or tap it it takes me to a screen where I'm able to modify the prompts that
       are used for the hourly generation ... save and cycle through presets ...
       a dice icon that if I click it, it actually shuffles between the prompts
       that I have saved" (operator, 2026-09-28). P opens the hourly prompts screen
       in this card: the saved presets (previous / next / the list), their words,
       Save, Save as new, Use next hour, Set active, Delete, and the recent hours.
       The dice turns the hourly shuffle on and off: each hour System 3 rolls one of
       the saved presets (its desk weights them - POOLS1 h3.hourly_preset). Nothing
       here renders; it changes what the one hourly render is told. */
    var pState = null, pView = null, pIndex = 0, pSelected = '', pBusy = false, pTimer = 0, pLoadedAt = 0;
    var pDrafts = {}, pDeleteArmed = '';
    var pButton = make('button', 'pav-p', 'P'); pButton.type = 'button';
    pButton.title = 'Hourly prompts: edit, save and cycle the presets the hourly render is told';
    pButton.setAttribute('aria-label', pButton.title); pButton.setAttribute('aria-expanded', 'false');
    var pDice = command('Shuffle the hourly prompts', 'm:casino', function () { setDice(!(pState && pState.dice)); });
    pDice.classList.add('pav-dice'); pDice.setAttribute('aria-pressed', 'false');
    h3Bar.insertBefore(pButton, h3Gear); h3Bar.insertBefore(pDice, h3Gear);
    function pBtn(title, icon, text, action) {
      var b = make('button', 'pav-pr-btn'); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
      if (root.pineIcon) b.innerHTML = root.pineIcon(icon);
      b.appendChild(make('span', '', text)); b.addEventListener('click', action); return b;
    }
    var pScreen = make('section', 'pav-prompts'); pScreen.hidden = true;
    pScreen.setAttribute('role', 'region'); pScreen.setAttribute('aria-label', 'Hourly prompts');
    var pTop = make('div', 'pav-pr-top');
    var pBack = pBtn('Back to the gallery', 'c:caret--left', 'Gallery', function () { showPrompts(false); });
    var pDiceBig = pBtn('Shuffle the hourly prompts: each hour System 3 rolls one of the saved presets', 'm:casino', 'Dice off',
      function () { setDice(!(pState && pState.dice)); });
    pDiceBig.classList.add('pav-pr-dice'); pDiceBig.setAttribute('aria-pressed', 'false');
    pTop.append(pBack, make('b', '', 'Hourly prompts'), pDiceBig);
    var pNextLine = make('div', 'pav-pr-next'), pNextWords = make('span', '', '');
    var pClearPin = pBtn('Unpin: the next hour goes back to the dice or the active preset', 'c:close--filled', 'Unpin',
      function () { pinNext({clear: true}); });
    pNextLine.append(pNextWords, pClearPin);
    var pCycle = make('div', 'pav-pr-cycle');
    var pPrev = command('Previous preset', 'c:caret--left', function () { cycle(-1); });
    var pPick = make('select', 'pav-pr-pick'); pPick.setAttribute('aria-label', 'Saved presets');
    var pNextPreset = command('Next preset', 'c:caret--right', function () { cycle(1); });
    var pCount = make('span', 'pav-pr-count', '');
    var pActive = pBtn('Every hour uses this preset while the dice are off', 'c:checkmark--filled', 'Set active', setActive);
    pCycle.append(pPrev, pPick, pNextPreset, pCount, pActive);
    var pOdds = make('p', 'pav-pr-odds', '');
    var pForm = make('form', 'pav-pr-form'); pForm.setAttribute('novalidate', '');
    var P_FIELDS = [
      ['name', 'Name', 'input', 'what this preset has people doing'],
      ['goal', 'Brief', 'textarea', '{conversation} is the hour\'s talk, {record} the record on air - leave them out for the same scene every time'],
      ['clip', 'Clip road', 'textarea', 'a dialogue clip is the reference; {goal} is the brief'],
      ['gallery', 'Gallery road', 'textarea', 'a gallery picture is the reference; {goal} is the brief'],
      ['host', 'Host road', 'textarea', 'the host\'s LoRA presents (only while the cast is on); {goal} is the brief'],
      ['speech', 'Line spoken', 'input', 'blank: pulled out of the brief, as before'],
      ['style', 'Style', 'input', 'one style term - blank: the gear\'s brief, else a polished broadcast commercial'],
      ['audio_direction', 'Audio direction', 'input', 'blank: the gear\'s brief'],
      ['constraints', 'Constraints', 'input', 'blank: the gear\'s brief'],
      /* [h3-overview] */
      ['kind', 'Kind', 'input', 'blank: these words. overview: a technical overview at a whiteboard - a rolled changelog feature, pitched by the model']];
    var pInputs = {}, pLabels = {};
    P_FIELDS.forEach(function (f) {
      var label = make('label', 'pav-pr-field'), input = make(f[2]);
      if (f[2] === 'textarea') input.rows = f[0] === 'goal' ? 3 : 2; else input.type = 'text';
      input.maxLength = f[0] === 'kind' ? 20 : f[0] === 'name' ? 60 : f[0] === 'goal' ? 1200 : f[2] === 'textarea' ? 1800 : f[0] === 'speech' ? 700 : f[0] === 'style' ? 120 : 400;
      input.setAttribute('aria-label', f[1]); input.addEventListener('input', paintEditState);
      var span = make('span', '', f[1]), hint = make('i', '', f[3]);
      label.append(span, hint, input); pForm.appendChild(label); pInputs[f[0]] = input;
      pLabels[f[0]] = {label: label, span: span, hint: hint, input: input};
    });
    /* [prompt-simple] "a simple toggle ... instead of having eight lines to do a
       prompt ... Basically I want to just type in what I want them to say and
       describe what I want them to do." (the operator) SIMPLE shows two boxes -
       what they say (the line spoken) and what they do (the brief); ADVANCED
       shows every field, as before. Hidden fields keep their words and are
       saved as they are. The choice is remembered on this screen. */
    var P_SIMPLE = {
      /* [prompt-simple] "allow me to name the preset that I'm saving" */
      name: ['Preset name', 'what this preset is called - type a new name, then Save as new to keep it as its own preset'],
      speech: ['What they say', 'the words spoken, exactly as written - {station} is the station\'s name'],
      goal: ['What they do', 'describe the action, the scene and the mood - {station} works here too'],
      kind: ['Kind', 'blank: what you typed above. overview: a technical overview - the model pitches a rolled changelog feature at a whiteboard']};
    var pMode = 'simple';
    try { pMode = root.localStorage.getItem('pinePromptMode') === 'advanced' ? 'advanced' : 'simple'; } catch (e) { /* default */ }
    var pModeBtn = pBtn('', 'c:settings--adjust', '', function () { setPromptMode(pMode === 'simple' ? 'advanced' : 'simple'); });
    pModeBtn.classList.add('pav-pr-mode');
    function setPromptMode(mode) {
      pMode = mode === 'advanced' ? 'advanced' : 'simple';
      try { root.localStorage.setItem('pinePromptMode', pMode); } catch (e) { /* this screen only */ }
      var simple = pMode === 'simple';
      P_FIELDS.forEach(function (f) {
        var L = pLabels[f[0]], s = simple && P_SIMPLE[f[0]];
        L.label.style.display = simple && !s ? 'none' : '';
        L.label.style.order = simple ? (f[0] === 'name' ? '0' : f[0] === 'speech' ? '1' : f[0] === 'kind' ? '3' : '2') : '';
        L.span.textContent = s ? s[0] : f[1];
        L.hint.textContent = s ? s[1] : f[3];
        L.input.setAttribute('aria-label', s ? s[0] : f[1]);
        if (f[0] === 'goal') L.input.rows = simple ? 4 : 3;
      });
      pModeBtn.lastChild.textContent = simple ? 'Simple' : 'Advanced';
      pModeBtn.title = simple ? 'Simple - just what they say and what they do. Tap for every field (Advanced)'
        : 'Advanced - every field. Tap for just what they say and what they do (Simple)';
      pModeBtn.setAttribute('aria-label', pModeBtn.title);
      pModeBtn.setAttribute('aria-pressed', String(!simple));
    }
    pTop.insertBefore(pModeBtn, pDiceBig);
    setPromptMode(pMode);
    pForm.addEventListener('submit', function (e) { e.preventDefault(); savePreset(); });
    var pActions = make('div', 'pav-pr-actions');
    var pSave = pBtn('Save these words to this preset', 'c:save', 'Save', savePreset);
    var pSaveNew = pBtn('Save these words as a new preset', 'c:add', 'Save as new', saveAsNew);
    var pUseNext = pBtn('The next hourly render is told these words, once', 'c:time', 'Use next hour', useNextHour);
    var pRevert = pBtn('Put back the saved words', 'c:renew', 'Revert', revertPreset);
    var pDelete = pBtn('Delete this preset', 'c:trash-can', 'Delete', deletePreset);
    pActions.append(pSave, pSaveNew, pUseNext, pRevert, pDelete);
    var pNote = make('p', 'pav-pr-note'); pNote.setAttribute('role', 'status');
    var pHoursHead = make('b', 'pav-pr-hours-head', 'Recent hours'), pHours = make('div', 'pav-pr-hours');
    pScreen.append(pTop, pNextLine, pCycle, pOdds, pForm, pActions, pNote, pHoursHead, pHours);
    function pCurrent() { return pView && pView.presets ? pView.presets[pIndex] || null : null; }
    function pValues() { var out = {}; P_FIELDS.forEach(function (f) { out[f[0]] = pInputs[f[0]].value; }); return out; }
    function pSame(a, b) { return P_FIELDS.every(function (f) { return String(a[f[0]] == null ? '' : a[f[0]]) === String(b[f[0]] == null ? '' : b[f[0]]); }); }
    function pFill(values) { P_FIELDS.forEach(function (f) { pInputs[f[0]].value = values && values[f[0]] != null ? String(values[f[0]]) : ''; }); }
    function pDirty() { var p = pCurrent(); return !!p && !pSame(pValues(), p); }
    function pStash() { var p = pCurrent(); if (!p) return; if (pDirty()) pDrafts[p.id] = pValues(); else delete pDrafts[p.id]; }
    function pFreeName(name) {
      var taken = ((pView && pView.presets) || []).map(function (p) { return String(p.name).toLowerCase(); });
      name = String(name || '').trim().slice(0, 60) || 'New preset';
      if (taken.indexOf(name.toLowerCase()) < 0) return name;
      for (var n = 2; n < 200; n++) {
        var tried = (name.slice(0, 52) + ' (' + n + ')');
        if (taken.indexOf(tried.toLowerCase()) < 0) return tried;
      }
      return name;
    }
    function pShow(at) {
      if (!pView || !pView.presets || !pView.presets.length) return;
      pIndex = (at + pView.presets.length) % pView.presets.length;
      var p = pView.presets[pIndex]; pSelected = p.id; pDeleteArmed = '';
      pFill(pDrafts[p.id] || p); paintScreen();
    }
    function cycle(step) { pStash(); pShow(pIndex + step); }
    pPick.addEventListener('change', function () { pStash(); pShow(Number(pPick.value) || 0); });
    function paintEditState() {
      var dirty = pDirty(), p = pCurrent();
      pSave.disabled = pBusy || !dirty; pRevert.disabled = !dirty; pSaveNew.disabled = pBusy;
      pUseNext.disabled = pBusy || !p; pDelete.disabled = pBusy || !p || ((pView && pView.presets) || []).length <= 1;
      pActive.disabled = pBusy || !p || !!(pState && p && pState.active === p.id);
      pActive.lastChild.textContent = pState && p && pState.active === p.id ? 'Active' : 'Set active';
      pDelete.lastChild.textContent = p && pDeleteArmed === p.id ? 'Tap again to delete' : 'Delete';
      if (p && pPick.options[pIndex]) pPick.options[pIndex].textContent = presetLabel(p, pIndex) + (dirty ? ' - edited' : '');
    }
    function presetLabel(p, at) {
      var odds = ((pView && pView.odds) || [])[at] || {};
      return p.name + (pState && pState.active === p.id ? ' (active)' : '')
        + (pState && pState.dice ? (odds.off ? ' - sits out' : odds.share != null ? ' - ' + odds.share + '%' : '') : '')
        + (pDrafts[p.id] && at !== pIndex ? ' - edited' : '');
    }
    function paintNextLine() {
      var s = pState || {}, nh = s.next_hour || {};
      var left = null;
      if (h3State && h3State.enabled !== false) left = Math.max(0, Number(h3State.seconds_remaining || 0) - (Date.now() / 1000 - Number(h3State.client_at || 0)));
      var last = s.last_hour;
      pNextWords.textContent = 'Next hour' + (left != null ? ' (in ' + h3Clock(left) + ')' : h3State && h3State.enabled === false ? ' (the hourly render is off)' : '')
        + ': ' + (nh.words || '...') + (last ? '. Last hour, ' + usedTime(last.at) + ': "' + ((last.preset || {}).name || '?') + '", ' + (last.how_words || '') + '.' : '');
      pClearPin.hidden = !s.next;
      var on = !!s.dice;
      pDiceBig.classList.toggle('on', on); pDiceBig.setAttribute('aria-pressed', String(on));
      pDiceBig.lastChild.textContent = on ? 'Dice on' : 'Dice off';
    }
    function paintScreen() {
      paintNextLine();
      var presets = (pView && pView.presets) || [];
      pPick.replaceChildren();
      presets.forEach(function (p, at) { var o = make('option', '', presetLabel(p, at)); o.value = String(at); pPick.appendChild(o); });
      pPick.value = String(pIndex);
      pCount.textContent = presets.length ? (pIndex + 1) + ' of ' + presets.length : 'no presets';
      var p = pCurrent(), s = pState || {}, odds = ((pView && pView.odds) || [])[pIndex] || {};
      if (!s.dice) pOdds.textContent = 'Dice off: every hour uses "' + (s.active_name || 'the active preset') + '". Turn the dice on to shuffle the '
        + presets.length + ' saved presets at each hour.';
      else if (p) pOdds.textContent = 'Dice on: "' + p.name + '" ' + (odds.off ? 'sits out - switched off on System 3\'s desk'
        : 'comes up ' + odds.share + '% of hours') + (!s.dice_live ? ' (System 3 is off: the station rolls, evenly)'
        : pView.desk_tabled ? (odds.on_desk ? ' (weight ' + odds.weight + ' on System 3\'s desk, POOLS1 ' + s.dice_key + ')'
          : ' (not on System 3\'s desk yet - weight 1; add it to POOLS1 ' + s.dice_key + ' to weight it)')
        : ' (the first roll puts the presets on System 3\'s desk, POOLS1 ' + s.dice_key + ', to be weighted)') + '.';
      paintHours(); paintEditState();
    }
    function paintHours() {
      var hours = (pView && pView.hours) || [];
      pHours.replaceChildren(); pHoursHead.hidden = !hours.length;
      hours.forEach(function (h) {
        var row = make('div', 'pav-pr-hour'), name = (h.preset && h.preset.name) || 'an hour';
        var words = Object.assign({}, h.fields || {});
        row.append(make('time', '', usedTime(h.at)), make('span', '', '"' + name + '" - ' + (h.how_words || h.how || '')),
          pBtn('The next hour is told this hour\'s words again', 'c:time', 'Again', function () {
            pinNext({preset: Object.assign({}, words, {name: name + ' again'})});
          }),
          pBtn('Keep this hour\'s words as a new preset', 'c:save', 'Keep', function () {
            pPost('/api/h3/prompts', Object.assign({}, words, {name: pFreeName(name + ' (' + usedTime(h.at) + ')')}), 'Kept as a new preset.');
          }),
          make('i', '', String(h.goal || '').slice(0, 220)));
        pHours.appendChild(row);
      });
    }
    function paintPromptButtons() {
      var s = pState || {}, on = !!s.dice, nh = (s.next_hour && s.next_hour.words) || '';
      pDice.setAttribute('aria-pressed', String(on)); pDice.classList.toggle('on', on);
      pDice.title = on ? 'Dice on - next hour: ' + nh + '. Tap to turn the shuffle off.'
        : 'Dice off - every hour uses "' + (s.active_name || 'the active preset') + '". Tap to shuffle the saved presets each hour.';
      pDice.setAttribute('aria-label', pDice.title);
      pButton.title = 'Hourly prompts - next hour: ' + (nh || 'unknown');
      pButton.setAttribute('aria-label', pButton.title); pButton.classList.toggle('pinned', !!s.next);
    }
    function applyPrompts(got, settled) {
      if (!got || typeof got !== 'object') return;
      if (got.presets) {
        pStash();
        if (settled) delete pDrafts[settled];        /* its words were just saved (or saved as new) */
        var want = got.saved || pSelected;
        pView = got;
        Object.keys(pDrafts).forEach(function (id) {
          var q = got.presets.find(function (x) { return x.id === id; });
          if (!q || pSame(pDrafts[id], q)) delete pDrafts[id];
        });
        var at = got.presets.findIndex(function (x) { return x.id === want; });
        if (at < 0) at = got.presets.findIndex(function (x) { return x.id === got.active; });
        pIndex = Math.max(0, at); pSelected = (got.presets[pIndex] || {}).id || '';
        pFill(pDrafts[pSelected] || got.presets[pIndex]);
      }
      pState = got; pLoadedAt = Date.now();
      paintPromptButtons();
      if (!pScreen.hidden) paintScreen();
    }
    function loadPrompts(full) {
      if (gone || !root.pineDesktop) return Promise.resolve();
      return root.pineDesktop.get('/api/h3/prompts' + (full ? '' : '?summary=1')).then(function (got) {
        if (!gone) applyPrompts(got);
      }).catch(function (err) { if (!gone && full) pNote.textContent = 'Could not load the hourly prompts: ' + ((err && err.message) || err); });
    }
    function pPost(route, body, done, settled) {
      if (gone) return Promise.resolve(null);
      if (pBusy) { pNote.textContent = 'Still saving the last change - try again in a moment.'; return Promise.resolve(null); }
      pBusy = true; paintEditState();
      return root.pineDesktop.post(route, body || {}).then(function (got) {
        if (gone) return null;
        applyPrompts(got, settled); if (done) pNote.textContent = typeof done === 'function' ? done(got) : done;
        return got;
      }).catch(function (err) {
        if (!gone) pNote.textContent = 'Not saved: ' + ((err && err.message) || err);
        return null;
      }).finally(function () { pBusy = false; if (!gone) paintEditState(); });
    }
    function setDice(on) {
      return pPost('/api/h3/prompts/dice', {on: !!on}, on ? 'Dice on: each hour System 3 rolls one of the saved presets.'
        : 'Dice off: every hour uses the active preset.');
    }
    function setActive() {
      var p = pCurrent(); if (!p) return;
      pPost('/api/h3/prompts/active', {id: p.id}, 'Every hour now uses "' + p.name + '" while the dice are off'
        + (pDirty() ? ' - its saved words; the edits here are not saved yet.' : '.'));
    }
    function savePreset() {
      var p = pCurrent(); if (!p) return;
      var v = pValues();
      if (!String(v.name || '').trim()) { pNote.textContent = 'Name the preset first.'; pInputs.name.focus(); return; }
      v.was = p.updated_at;
      pPost('/api/h3/prompts/' + encodeURIComponent(p.id), v, 'Saved "' + String(v.name).trim() + '".', p.id);
    }
    function saveAsNew() {
      var p = pCurrent(), v = pValues();
      v.name = pFreeName(v.name || (p && p.name) || 'New preset');
      pPost('/api/h3/prompts', v, 'Saved as a new preset, "' + v.name + '".', p ? p.id : '');
    }
    function useNextHour() {
      var p = pCurrent(); if (!p) return;
      pinNext(pDirty() ? {preset: pValues()} : {preset_id: p.id});
    }
    function pinNext(body) {
      return pPost('/api/h3/prompts/next', body, function (got) {
        var next = (got && got.next) || null;
        return body.clear ? 'Unpinned: the next hour goes back to ' + (got && got.dice ? 'the dice.' : 'the active preset.')
          : next ? 'The next hourly render is told "' + next.name + '", once.' : 'Pinned.';
      });
    }
    function revertPreset() {
      var p = pCurrent(); if (!p) return;
      delete pDrafts[p.id]; pFill(p); paintEditState(); pNote.textContent = 'The saved words of "' + p.name + '" are back.';
    }
    function deletePreset() {
      var p = pCurrent(); if (!p) return;
      if (pDeleteArmed !== p.id) {       /* no window.confirm: the desk's shell has none - a second tap */
        pDeleteArmed = p.id; paintEditState(); pNote.textContent = 'Delete "' + p.name + '"? Tap Delete again.';
        setTimeout(function () { if (pDeleteArmed === p.id) { pDeleteArmed = ''; if (!gone) paintEditState(); } }, 4000);
        return;
      }
      pDeleteArmed = ''; delete pDrafts[p.id];
      pPost('/api/h3/prompts/' + encodeURIComponent(p.id) + '/delete', {}, 'Deleted "' + p.name + '".');
    }
    function showPrompts(on) {
      if (!gallery || gone) return;
      if (!on) pStash();
      pScreen.hidden = !on; box.classList.toggle('pav-on-prompts', !!on);
      pButton.setAttribute('aria-expanded', String(!!on)); pButton.classList.toggle('open', !!on);
      if (on) {
        var playing = stage && stage.querySelector('video');
        if (playing && !playing.paused) { try { playing.pause(); } catch (e) { /* nothing to pause */ } }
        qualityPanel.hidden = true; pNote.textContent = pView ? '' : 'Loading the hourly prompts...';
        if (pView) paintScreen();
        loadPrompts(true); box.scrollTop = 0; pBack.focus();
      } else if (pButton.isConnected) pButton.focus();
    }
    pButton.addEventListener('click', function () { showPrompts(pScreen.hidden); });
    /* [#1450c] BACK closes the topmost overlay, one at a time: this card's P screen
       first, then the card itself - the kiosk walks history only when nothing answers */
    var pBackOff = function () {};
    if (root.PineDismiss && typeof root.PineDismiss.onBack === 'function') {
      pBackOff = root.PineDismiss.onBack(function () {
        if (gone) return null;
        if (gallery && !pScreen.hidden) return {node: pScreen, close: function () { showPrompts(false); }};
        return {node: box, close: close};
      });
    }
    if (gallery) {
      loadPrompts(false);
      pTimer = setInterval(function () {
        if (gone) return;
        if (!pScreen.hidden) paintNextLine();
        if (!pBusy && Date.now() - pLoadedAt > 30000) { pLoadedAt = Date.now(); loadPrompts(false); }
      }, 1000);
    }
    var qPreset = make('select'); qPreset.setAttribute('aria-label', 'H3 quality preset');
    var qSteps = make('select'); qSteps.setAttribute('aria-label', 'steps');
    var qSize = make('select'); qSize.setAttribute('aria-label', 'frame size');
    var qSecs = make('select'); qSecs.setAttribute('aria-label', 'longest clip');
    var qBox = make('span', 'pav-quality-box', '');
    /* [h3-budget] measured on this box: double ran a 10 s render in 45-50 min.
       Every render is fitted to this budget (the frame shrinks, never the length). */
    var qBudget = make('select'); qBudget.setAttribute('aria-label', 'render-time budget');
    function qMin(s) { return s >= 60 ? Math.round(s / 60) + ' min' : Math.round(s) + ' s'; }
    var qApply = make('button', '', 'Apply'); qApply.type = 'button';
    var qNote = make('span', 'pav-quality-note', 'Doubling the frame quadruples the pixels the sampler holds: the double profile steps down by itself while the box is hot or short of room.');
    var Q_SIZES = [[640, 384], [960, 576], [1280, 768], [1536, 896]];
    function qOpt(sel, value, label, selected) { var o = make('option', '', label); o.value = String(value); if (selected) o.selected = true; sel.appendChild(o); return o; }
    function paintQuality(state) {
      var q = (state && state.quality) || {}; var presets = (state && state.presets) || {};
      qPreset.replaceChildren();
      var est = (state && state.estimates) || {};
      Object.keys(presets).forEach(function (k) { qOpt(qPreset, k, k + ' - ' + presets[k].steps + ' steps, ' + presets[k].width + 'x' + presets[k].height
        + (est[k] ? ' (~' + qMin(est[k]) + ' for 10 s)' : ''), q.preset === k); });
      qBudget.replaceChildren();
      ((state && state.budget_choices) || [300, 600, 900, 1800, 3600, 0]).forEach(function (n) {
        qOpt(qBudget, n, n ? 'fit each render to ' + qMin(n) : 'no time limit', Number(q.budget_s == null ? 900 : q.budget_s) === Number(n));
      });
      qOpt(qPreset, 'custom', 'custom', q.preset === 'custom' || !presets[q.preset]);
      qSteps.replaceChildren();
      /* [h3-cinematic] a step count names its path: the turbo LoRA's 4-12, the
         base model's 20-30 (the cinematic preset) - the lists never overlap */
      var baseSteps = q.turbo === false || Number(q.steps) >= 16;
      (baseSteps ? ((state && state.base_step_choices) || [20, 25, 30]) : ((state && state.step_choices) || [4, 6, 8, 12]))
        .forEach(function (n) { qOpt(qSteps, n, n + ' steps' + (baseSteps ? ' (base model)' : ''), Number(q.steps) === Number(n)); });
      qSize.replaceChildren();
      var known = false;
      Q_SIZES.forEach(function (wh) {
        var on = wh[0] === Number(q.width) && wh[1] === Number(q.height); known = known || on;
        qOpt(qSize, wh[0] + 'x' + wh[1], wh[0] + ' x ' + wh[1] + (wh[0] === 640 ? ' (standard)' : wh[0] === 1280 ? ' (double)' : ''), on);
      });
      if (!known && q.width) qOpt(qSize, q.width + 'x' + q.height, q.width + ' x ' + q.height, true);
      qSecs.replaceChildren();
      ((state && state.frame_choices) || [73, 124, 169, 241, 289, 361]).forEach(function (f) { qOpt(qSecs, f, 'up to ' + Math.round(f / 24) + ' s', Number(q.max_frames) === Number(f)); });
      paintKnobs(state);
      paintCast(state);                                          /* [h3-cast] */
      var box = (state && state.box) || {};
      qBox.textContent = 'box now: ' + (box.hottest_c != null ? Math.round(box.hottest_c) + ' C of ' + Math.round(box.ceiling_c || 90) + ' C' : 'heat unknown')
        + ', ' + (box.available_gb != null ? Math.round(box.available_gb) + ' GB free (the double frame wants ' + Math.round((box.floor_gb || 60) + 30) + ')' : 'memory unknown');
    }
    qPreset.addEventListener('change', function () {
      var p = h3State && h3State.presets && h3State.presets[qPreset.value];
      if (p) paintQuality(Object.assign({}, h3State, {quality: p}));
      if (qPreset.value === 'cinematic') {
        qNote.textContent = 'Cinematic runs the base model without the turbo LoRA: ' + ((p && p.steps) || 20) + ' steps, clips up to 5 s, '
          + 'about three times the render time. It starts only at or under ' + Math.round((h3State && h3State.cinematic_heat_c) || 80)
          + ' C and never renders the hourly ad - otherwise that render steps down to double and says why.';
      }
    });
    [qSteps, qSize, qSecs].forEach(function (sel) { sel.addEventListener('change', function () { qPreset.value = 'custom'; }); });
    qApply.addEventListener('click', function () {
      var wh = String(qSize.value).split('x');
      var body = {quality: {preset: qPreset.value, steps: Number(qSteps.value), width: Number(wh[0]), height: Number(wh[1]), max_frames: Number(qSecs.value),
          easycache: qCache.checked, shift: qShiftOn.checked ? [Number(qShiftV.value) || 12, Number(qShiftA.value) || 3] : null,
          sampler: qSampler.value, scheduler: qSched.value, turbo: Number(qSteps.value) < 16,   /* [h3-cinematic] */
          budget_s: Number(qBudget.value)},                                                     /* [h3-budget] */
        brief: {style: bStyle.value, follow: bFollow.value, shots: bShots.value, constraints: bCons.value, audio_direction: bAudio.value}};
      qApply.disabled = true; qNote.textContent = 'saving...';
      root.pineDesktop.post('/api/h3/hourly', body).then(function (state) {
        h3State = state || {}; h3State.client_at = Date.now() / 1000; paintH3(); paintQuality(h3State);
        var q = h3State.quality || {};
        var b = h3State.brief || {};
        qNote.textContent = 'Every H3 render now runs at ' + q.steps + ' steps, ' + q.width + ' x ' + q.height + ', up to ' + Math.round((q.max_frames || 0) / 24) + ' s'
          + (q.easycache === false ? ', no cache' : '') + (q.shift ? ', shift ' + q.shift.join('/') : '') + (q.sampler && q.sampler !== 'turbo' ? ', ' + q.sampler + '+' + q.scheduler : '')
          + '; the brief: ' + (b.style || 'style per road') + ', ' + (FOLLOW_WORDS[b.follow] || 'auto') + ', ' + (SHOT_WORDS[b.shots] || 'by length') + '. Stepped down while the box is hot or full.';
      }).catch(function (err) { qNote.textContent = 'Could not save: ' + ((err && err.message) || err); })
        .finally(function () { qApply.disabled = false; });
    });
    /* [h3-brief-config] "add the configuration for these to the H3 Pine box
       menu so that I can utilize them in prompts": the graph knobs and the
       brief's knobs sit under the quality row. Blank means the compiler's own
       default, shown as the placeholder. */
    var qCache = make('input'); qCache.type = 'checkbox'; qCache.checked = true;
    var qCacheLabel = make('label', 'pav-q-check'); qCacheLabel.append(qCache, make('span', '', 'EasyCache'));
    var qShiftOn = make('input'); qShiftOn.type = 'checkbox';
    var qShiftV = make('input'); qShiftV.type = 'number'; qShiftV.min = '0.01'; qShiftV.max = '100'; qShiftV.step = '0.5'; qShiftV.value = '12'; qShiftV.setAttribute('aria-label', 'video shift');
    var qShiftA = make('input'); qShiftA.type = 'number'; qShiftA.min = '0.01'; qShiftA.max = '100'; qShiftA.step = '0.5'; qShiftA.value = '3'; qShiftA.setAttribute('aria-label', 'audio shift');
    var qShiftLabel = make('label', 'pav-q-check'); qShiftLabel.append(qShiftOn, make('span', '', 'sigma shift'), qShiftV, qShiftA);
    var qSampler = make('select'); qSampler.setAttribute('aria-label', 'sampler');
    var qSched = make('select'); qSched.setAttribute('aria-label', 'scheduler');
    var bStyle = make('input'); bStyle.type = 'text'; bStyle.maxLength = 120; bStyle.placeholder = 'style term - blank: one per road'; bStyle.setAttribute('aria-label', 'style term');
    var bFollow = make('select'); bFollow.setAttribute('aria-label', 'shots follow');
    var bShots = make('select'); bShots.setAttribute('aria-label', 'shot count');
    var bCons = make('input'); bCons.type = 'text'; bCons.maxLength = 400; bCons.setAttribute('aria-label', 'constraints');
    var bAudio = make('input'); bAudio.type = 'text'; bAudio.maxLength = 400; bAudio.setAttribute('aria-label', 'audio direction');
    var FOLLOW_WORDS = {auto: 'shots follow: auto (the reference on a reference road)', reference: 'shots follow the reference', presenter: 'shots: a presenter to camera'};
    var SHOT_WORDS = {auto: 'shot count: by length', '1': 'one shot', '2': 'two shots', '3': 'three shots'};
    var qualityRow = make('div', 'pav-quality-row'); qualityRow.append(make('b', '', 'H3 quality'), qPreset, qSteps, qSize, qSecs, qBudget, qApply, qBox);
    var graphRow = make('div', 'pav-quality-row'); graphRow.append(make('b', '', 'Graph'), qCacheLabel, qShiftLabel, qSampler, qSched);
    var briefRow = make('div', 'pav-quality-row'); briefRow.append(make('b', '', 'Brief'), bStyle, bFollow, bShots, bCons, bAudio);
    function paintKnobs(state) {
      var q = (state && state.quality) || {}; var b = (state && state.brief) || {};
      qCache.checked = q.easycache !== false;
      qShiftOn.checked = !!(q.shift && q.shift.length === 2);
      if (q.shift && q.shift.length === 2) { qShiftV.value = String(q.shift[0]); qShiftA.value = String(q.shift[1]); }
      qSampler.replaceChildren(); ((state && state.sampler_choices) || ['turbo', 'euler']).forEach(function (x) { qOpt(qSampler, x, x === 'turbo' ? 'turbo sampler' : 'sampler: ' + x, (q.sampler || 'turbo') === x); });
      qSched.replaceChildren(); ((state && state.scheduler_choices) || ['simple', 'beta']).forEach(function (x) { qOpt(qSched, x, 'scheduler: ' + x, (q.scheduler || 'simple') === x); });
      bStyle.value = b.style || '';
      bFollow.replaceChildren(); ((state && state.follow_choices) || ['auto', 'reference', 'presenter']).forEach(function (x) { qOpt(bFollow, x, FOLLOW_WORDS[x] || x, (b.follow || 'auto') === x); });
      bShots.replaceChildren(); ((state && state.shot_choices) || ['auto', '1', '2', '3']).forEach(function (x) { qOpt(bShots, x, SHOT_WORDS[x] || x, (b.shots || 'auto') === x); });
      bCons.value = b.constraints || ''; bCons.placeholder = (state && state.default_constraints) || 'constraints - blank: standard';
      bAudio.value = b.audio_direction || ''; bAudio.placeholder = (state && state.default_audio) || 'audio direction - blank: standard';
    }
    /* [h3-cast] the host's face: an identity LoRA trained on the host (on the
       box, by the pinebox-h3-cast service), riding the text road's renders and
       the host's share of the hourly stingers. Train asks the box to make or
       remake it; the run pauses itself while the box is hot, full or
       rendering, and this row shows where it is. */
    var cOn = make('input'); cOn.type = 'checkbox';
    var cOnLabel = make('label', 'pav-q-check'); cOnLabel.append(cOn, make('span', '', 'host LoRA'));
    var cStrength = make('input'); cStrength.type = 'range'; cStrength.min = '0'; cStrength.max = '1.5'; cStrength.step = '0.05'; cStrength.value = '0.9';
    cStrength.setAttribute('aria-label', 'host LoRA strength');
    var cStrengthVal = make('span', 'pav-cast-val', '0.90');
    cStrength.addEventListener('input', function () { cStrengthVal.textContent = Number(cStrength.value).toFixed(2); });
    var cShare = make('select'); cShare.setAttribute('aria-label', 'hourly stingers the host presents');
    [0, 10, 20, 30, 50, 100].forEach(function (n) { qOpt(cShare, n, n ? 'host presents ' + n + '% of hours' : 'host presents no hours', false); });
    var cApply = make('button', '', 'Save cast'); cApply.type = 'button';
    var cTrain = make('button', '', 'Train'); cTrain.type = 'button';
    var cStop = make('button', '', 'Stop'); cStop.type = 'button'; cStop.hidden = true;
    var cLook = make('input'); cLook.type = 'text'; cLook.maxLength = 600;
    cLook.placeholder = 'how the host looks - blank keeps the last look'; cLook.setAttribute('aria-label', 'how the host looks');
    var cState = make('span', 'pav-cast-state', '');
    var castRow = make('div', 'pav-quality-row pav-cast'); castRow.append(make('b', '', 'Cast'), cOnLabel, cStrength, cStrengthVal, cShare, cApply, cLook, cTrain, cStop, cState);
    var CAST_BUSY = {preparing: 1, portraits: 1, caching: 1, training: 1, paused: 1, installing: 1, testing: 1};
    function paintCast(state) {
      var c = (state && state.cast) || {}; var st = (state && state.cast_status) || {};
      cOn.checked = !!c.on;
      cStrength.value = String(c.strength != null ? c.strength : 0.9); cStrengthVal.textContent = Number(cStrength.value).toFixed(2);
      var share = Number((state && state.host_share) || 0);
      Array.prototype.forEach.call(cShare.options, function (o) { o.selected = Number(o.value) === share; });
      var lora = c.lora || st.lora || '';
      cOn.disabled = !lora;
      var busy = !!CAST_BUSY[st.state];
      cTrain.hidden = busy; cStop.hidden = !busy;
      cTrain.textContent = lora ? 'Retrain' : 'Train';
      var line = st.state === 'never trained' ? 'not trained yet - Train makes the host\'s portraits and trains the LoRA on the box (hours; it pauses whenever the box is hot or rendering)'
        : (st.state || 'unknown') + (st.step != null && st.of ? ' - step ' + st.step + ' of ' + st.of : '')
          + (st.why ? ' - ' + st.why : '') + (st.temp_c != null ? ' - box ' + Math.round(st.temp_c) + ' C' : '');
      cState.textContent = (lora ? lora + ' (trigger "' + (c.trigger || 'pinehost') + '") - ' : '') + line + (st.kick_waiting ? ' - a request is waiting for the box' : '');
    }
    cApply.addEventListener('click', function () {
      var st = (h3State && h3State.cast_status) || {}; var c = (h3State && h3State.cast) || {};
      var body = {cast: {on: cOn.checked, strength: Number(cStrength.value), lora: c.lora || st.lora || ''}, host_share: Number(cShare.value)};
      cApply.disabled = true;
      root.pineDesktop.post('/api/h3/hourly', body).then(function (state) {
        h3State = state || {}; h3State.client_at = Date.now() / 1000; paintCast(h3State);
      }).catch(function (err) { cState.textContent = 'Could not save: ' + ((err && err.message) || err); })
        .finally(function () { cApply.disabled = false; });
    });
    cTrain.addEventListener('click', function () {
      var look = String(cLook.value || '').trim();   /* no window.prompt: the desk's shell has none */
      cTrain.disabled = true;
      root.pineDesktop.post('/api/h3/cast/train', {look: look, fresh: !!look, steps: 600}).then(function (got) {
        if (h3State) h3State.cast_status = (got && got.status) || h3State.cast_status;
        paintCast(h3State); loadH3();
      }).catch(function (err) { cState.textContent = 'Could not ask: ' + ((err && err.message) || err); })
        .finally(function () { cTrain.disabled = false; });
    });
    cStop.addEventListener('click', function () {
      cStop.disabled = true;
      root.pineDesktop.post('/api/h3/cast/stop', {}).then(function () { loadH3(); })
        .finally(function () { cStop.disabled = false; });
    });
    qualityPanel.append(qualityRow, graphRow, briefRow, castRow, qNote);
    if (gallery) head.insertBefore(h3Bar, position);
    function h3Clock(seconds) {
      seconds = Math.max(0, Math.floor(Number(seconds) || 0));
      var hours = Math.floor(seconds / 3600), minutes = Math.floor((seconds % 3600) / 60);
      var tail = String(seconds % 60).padStart(2, '0');
      return hours ? hours + ':' + String(minutes).padStart(2, '0') + ':' + tail : minutes + ':' + tail;
    }
    function paintH3() {
      if (!gallery || !h3State) return;
      var enabled = h3State.enabled !== false;
      h3Toggle.checked = enabled; h3Bar.classList.toggle('off', !enabled);
      if (!enabled) { h3Fill.style.width = '0%'; h3Time.textContent = 'off'; return; }
      var elapsed = Date.now() / 1000 - Number(h3State.client_at || 0);
      var remaining = Math.max(0, Number(h3State.seconds_remaining || 0) - elapsed);
      var period = Math.max(1, Number(h3State.period_seconds || 3600));
      h3Fill.style.width = (Math.max(0, Math.min(1, 1 - remaining / period)) * 100).toFixed(1) + '%';
      h3Time.textContent = h3Clock(remaining);
      h3Bar.title = h3State.radio_on === false ? 'Station is off; render waits for broadcast'
        : 'Next hourly H3 render in ' + h3Clock(remaining);
    }
    function loadH3() {
      if (!gallery || gone || h3Loading || h3Toggle.disabled) return Promise.resolve();
      h3Loading = true;
      return root.pineDesktop.get('/api/h3/hourly').then(function (state) {
        if (gone) return;
        h3State = state || {}; h3State.client_at = Date.now() / 1000; paintH3();
        if (!qualityPanel.hidden) paintQuality(h3State);            /* [h3-quality] */
      }).catch(function () { if (!gone) h3Time.textContent = 'err'; })
        .finally(function () { h3Loading = false; });
    }
    h3Toggle.addEventListener('change', function () {
      h3Toggle.disabled = true;
      root.pineDesktop.post('/api/h3/hourly', {enabled: !!h3Toggle.checked}).then(function (state) {
        h3State = state || {}; h3State.client_at = Date.now() / 1000; paintH3();
        if (!qualityPanel.hidden) paintQuality(h3State);            /* [h3-quality] */
      }).catch(function () { h3Toggle.checked = !h3Toggle.checked; })
        .finally(function () { h3Toggle.disabled = false; });
    });
    if (gallery) { loadH3(); h3Timer = setInterval(function () {
      paintH3();
      if (!h3State || Date.now() / 1000 - h3State.client_at >= 15) loadH3();
    }, 1000); }
    var more = command('Load ten more items', 'c:add', function () { loadPage(10); });
    more.disabled = true;
    if (gallery) head.insertBefore(more, position);
    var posters = {}, posterQueue = [], posterActive = 0, posterObserver = null;
    function pumpPosters() {
      while (!gone && posterActive < 2 && posterQueue.length) {
        var item = posterQueue.shift();
        if (!item.image.isConnected) continue;
        posterActive++;
        (function (entry) {
          root.pineDesktop.get('/api/generations/poster-url/' + encodeURIComponent(entry.file)).then(function (got) {
            if (gone || !got.poster) return;
            posters[entry.file] = typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(got.poster) : got.poster;
            if (entry.image.isConnected) entry.image.src = posters[entry.file];
          }).catch(function () { /* The branded thumbnail remains available for missing sources. */ })
            .finally(function () { posterActive--; pumpPosters(); });
        }(item));
      }
    }
    var previous = command('Previous ad', 'c:caret--left', function () {
      if (index + 1 < rows.length) { index++; paint(); }
      else if (cursor || pendingRows.length) loadPage().then(function () { if (index + 1 < rows.length) { index++; paint(); } });
    });
    var next = command('Next ad', 'c:caret--right', function () { if (index > 0) { index--; paint(); } });
    head.appendChild(previous); head.appendChild(next); box.appendChild(head);
    if (gallery) box.appendChild(qualityPanel);                         /* [h3-quality] */
    if (gallery) box.appendChild(pScreen);                              /* [h3-prompts] the P screen */
    var strip = make('div', 'pav-strip'); strip.setAttribute('aria-label', 'Generated media');
    if (gallery) box.appendChild(strip);
    var motion = command('Pause gallery scrolling', 'c:pause--filled', function () {
      motion.dataset.paused = motion.dataset.paused === 'yes' ? '' : 'yes';
      motion.title = motion.dataset.paused ? 'Resume gallery scrolling' : 'Pause gallery scrolling';
      motion.setAttribute('aria-label', motion.title);
      if (root.pineIcon) motion.innerHTML = root.pineIcon(motion.dataset.paused ? 'c:caret--right' : 'c:pause--filled');
    });
    if (gallery) head.appendChild(motion);
    /* [autoscroll-rule] a hand on the strip stops the crawl until the
       operator presses play on it again - it used to take the strip back
       five seconds later, from under whatever they were looking at. */
    function holdCrawl() {
      if (motion.dataset.paused === 'yes') return;
      motion.dataset.paused = 'yes';
      motion.title = 'Resume gallery scrolling';
      motion.setAttribute('aria-label', motion.title);
      if (root.pineIcon) motion.innerHTML = root.pineIcon('c:caret--right');
    }
    ['pointerdown', 'wheel', 'focusin'].forEach(function (name) {
      strip.addEventListener(name, holdCrawl, {passive:true});
    });
    var description = make('p', 'pav-description'); box.appendChild(description);
    var stage = make('div', 'pav-stage'); box.appendChild(stage);
    /* [h3-prompts] "see the prompts used with a video on the main gallery popup
       under the video in a section able to be expanded with a tick showing the
       prompts used with the video and allowing them to be reused": under the
       video's own bar, above Generated / Original. Collapsed until the tick is
       pressed (and it stays as it was left while the gallery moves on). */
    var used = make('section', 'pav-used'); used.setAttribute('aria-label', 'Prompts used'); used.hidden = true;
    var usedTick = make('button', 'pav-used-tick'); usedTick.type = 'button'; usedTick.setAttribute('aria-expanded', 'false');
    if (root.pineIcon) usedTick.innerHTML = root.pineIcon('c:caret--right');
    var usedSum = make('span', 'pav-used-sum', '');
    usedTick.append(make('b', '', 'Prompts used'), usedSum);
    var usedBody = make('div', 'pav-used-body'); usedBody.hidden = true;
    used.append(usedTick, usedBody); box.appendChild(used);
    var usedOpen = false, usedRow = null, usedMsg = null;
    usedTick.addEventListener('click', function () {
      usedOpen = !usedOpen; paintUsed(usedRow);
      if (usedOpen && used.scrollIntoView) used.scrollIntoView({block: 'nearest'});
    });
    function usedSay(words) { if (usedMsg) usedMsg.textContent = words; }
    function usedName(row, w) {
      var stem = String(mediaFile(row) || '').replace(/\.[^.]+$/, '');
      return pFreeName(w.recorded ? w.preset + (stem ? ' (' + stem + ')' : ' again') : 'From ' + (stem || 'a video'));
    }
    function rollStage(into, rec, compact) {
      var rowsOf = rollRows(rec), speech = String((rec && rec.speech) || '');
      if (!rowsOf.length) return null;
      if (root.PineRollTag && typeof root.PineRollTag.mount === 'function') {
        try {
          return root.PineRollTag.mount(into, {who: 'dj', name: 'PINE BOX AD', text: speech,
            row: {text: speech, who: 'dj', kind: 'ad', name: 'PINE BOX AD'}},
            {title: 'How the roulette rolled this ad', compact: !!compact,
             data: {rows: rowsOf, sources: {main: '', others: [], why: {}}}});
        } catch (e) { /* the rolodex below stands in */ }
      }
      var reels = rowsOf.map(function (r) {
        return {name: r.table, picked: r.main.label, opts: r.main.opts, dice: r.main.dice,
          index: r.main.counted ? r.main.index : r.main.hit + 1, of: r.main.of};
      });
      into.appendChild(rolodex(reels));
      return null;
    }
    function paintRollHead(row) {
      var rec = row && row.h3_prompts && typeof row.h3_prompts === 'object' ? row.h3_prompts : null;
      if (rec === rollRec && (rollTag || !rollHead.hidden)) return;   /* the same ad: let it play on */
      rollRec = rec;
      if (rollTag) { try { rollTag.dispose(); } catch (e) { /* gone already */ } rollTag = null; }
      rollHead.replaceChildren();
      rollHead.hidden = !rollRows(rec).length;
      if (rollHead.hidden) return;
      var inner = make('div', 'pav-rollhead-in');
      rollHead.appendChild(inner);
      rollTag = rollStage(inner, rec, true);
    }
    function openRollDetails() {
      if (!rollRec) return;
      var old = document.getElementById('pavRollPop');
      if (old) old.remove();
      var pop = make('section', 'pav-rollpop'); pop.id = 'pavRollPop';
      pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', 'How the roulette rolled this ad');
      pop.appendChild(make('b', 'pav-rollpop-title', 'How the roulette rolled this ad'));
      var w = usedWords(usedRow || {});
      if (w.recorded) pop.appendChild(make('p', 'pav-used-meta', 'Preset "' + w.preset + '" - ' + w.how
        + (w.road ? ' - ' + w.road : '') + (w.at ? ' - the hour of ' + usedTime(w.at) : '')));
      var stageBox = make('div', 'pav-rollpop-stage');
      pop.appendChild(stageBox);
      var tag = rollStage(stageBox, rollRec, false);
      var list = make('div', 'pav-rollpop-rolls');
      rollRows(rollRec).forEach(function (r) {
        var m = r.main, line = make('div', 'pav-rollpop-row');
        line.append(make('span', 'pav-rollpop-name', r.table),
          make('span', 'pav-rollpop-got', m.label + '  -  d100 ' + m.dice + ', '
            + (m.counted ? m.index : m.hit + 1) + ' of ' + m.of));
        if (m.opts.length > 1) line.appendChild(make('span', 'pav-rollpop-opts', 'from: ' + m.opts.join('  |  ')));
        list.appendChild(line);
      });
      pop.appendChild(list);
      w.items.forEach(function (item) {
        if (item.reels) return;
        var cell = make('div', 'pav-used-item');
        cell.append(make('div', 'pav-used-label', item.label), make('pre', 'pav-used-text', item.text));
        pop.appendChild(cell);
      });
      var close = function () { if (tag) { try { tag.dispose(); } catch (e) { /* gone */ } } pop.remove(); };
      document.body.appendChild(pop);
      if (typeof root.pineCloseX === 'function') {
        try { root.pineCloseX(pop, close, {label: 'Close the roll'}); } catch (e) { /* Escape still closes */ }
      }
    }
    rollHead.addEventListener('click', function (ev) { ev.stopPropagation(); openRollDetails(); });
    rollHead.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openRollDetails(); }
    });
    function paintUsed(row) {
      usedRow = row || null; used.hidden = !usedRow;
      paintRollHead(usedRow);                                       /* [ad-roll] */
      var w = usedWords(usedRow || {});
      usedSum.textContent = w.summary;
      usedTick.setAttribute('aria-expanded', String(usedOpen)); used.classList.toggle('open', usedOpen);
      usedBody.hidden = !usedOpen; usedBody.replaceChildren(); usedMsg = null;
      if (!usedOpen) return;
      if (w.recorded) usedBody.appendChild(make('p', 'pav-used-meta', 'Preset "' + w.preset + '" - ' + w.how
        + (w.road ? ' - ' + w.road : '') + (w.at ? ' - the hour of ' + usedTime(w.at) : '')));
      if (w.note) usedBody.appendChild(make('p', 'pav-used-note', w.note));
      w.items.forEach(function (item) {
        var cell = make('div', 'pav-used-item'), label = make('div', 'pav-used-label');
        var copy = command('Copy the ' + item.label.toLowerCase(), 'c:copy--to-clipboard', function () {
          copyWords(item.text).then(function () { usedSay('Copied the ' + item.label.toLowerCase() + '.'); },
            function () { usedSay('Could not copy - select the words instead.'); });
        });
        label.append(make('span', '', item.label), copy);
        if (item.reels) cell.append(label, rolodex(item.reels));   /* [h3-slot-roll] */
        else cell.append(label, make('pre', 'pav-used-text', item.text));
        usedBody.appendChild(cell);
      });
      if (w.reusable && usedRow && usedRow.prompt_id) {
        var pid = usedRow.prompt_id, acts = make('div', 'pav-used-actions'), naming = make('div', 'pav-used-name');
        var nameInput = make('input'); nameInput.type = 'text'; nameInput.maxLength = 60;
        nameInput.setAttribute('aria-label', 'Name for the new preset'); nameInput.value = usedName(usedRow, w);
        naming.hidden = true;
        acts.append(
          pBtn('Copy every prompt above', 'c:copy--to-clipboard', 'Copy all', function () {
            copyWords(w.items.map(function (i) { return i.label + ':\n' + i.text; }).join('\n\n')).then(
              function () { usedSay('Copied every prompt.'); }, function () { usedSay('Could not copy - select the words instead.'); });
          }),
          pBtn('The next hourly render is told these words, once', 'c:time', 'Use for the next hour', function () {
            pPost('/api/h3/prompts/next', {from_prompt_id: pid}).then(function (got) {
              if (got) usedSay('The next hourly render is told "' + ((got.next || {}).name || 'these words') + '", once.');
              else usedSay(pNote.textContent || 'Not pinned.');
            });
          }),
          pBtn('Keep these words as a saved preset', 'c:save', 'Save as preset', function () {
            naming.hidden = !naming.hidden;
            if (naming.hidden) return;
            var first = nameInput.value = usedName(usedRow, w); nameInput.focus();
            /* the names already taken are in the full view; the gallery has only the summary until P opens */
            if (!pView) loadPrompts(true).then(function () { if (!naming.hidden && nameInput.value === first) nameInput.value = usedName(usedRow, w); });
          }));
        naming.append(nameInput, pBtn('Save the preset', 'c:save', 'Save', function () {
          var name = String(nameInput.value || '').trim();
          if (!name) { nameInput.focus(); return; }
          pPost('/api/h3/prompts', {from_prompt_id: pid, name: name}).then(function (got) {
            if (got) { naming.hidden = true; usedSay('Saved as the preset "' + name + '" - it is in P.'); }
            else usedSay(pNote.textContent || 'Not saved.');
          });
        }));
        usedBody.append(acts, naming);
      }
      usedMsg = make('p', 'pav-used-msg'); usedMsg.setAttribute('role', 'status'); usedBody.appendChild(usedMsg);
    }
    var modes = make('div', 'pav-modes'); modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', 'Video source');
    var generatedButton = make('button', '', 'Generated'), originalButton = make('button', '', 'Original');
    generatedButton.type = originalButton.type = 'button'; originalButton.disabled = true;
    modes.append(generatedButton, originalButton); box.appendChild(modes);
    generatedButton.addEventListener('click', function () { if (original) { original = false; paint(true); } });
    originalButton.addEventListener('click', function () { if (!original) { original = true; paint(true); } });
    var imageForm = make('div', 'pav-image-prompt'); imageForm.hidden = true;
    var imageMode = make('select'); imageMode.setAttribute('aria-label', 'H3 input type');
    ['Prompt', 'Dialogue'].forEach(function (label) {
      var option = make('option', '', label); option.value = label.toLowerCase(); imageMode.appendChild(option);
    });
    var imageText = make('textarea'); imageText.rows = 2; imageText.maxLength = 800;
    imageText.placeholder = 'Prompt or dialogue for H3...'; imageText.setAttribute('aria-label', 'H3 prompt or dialogue');
    imageForm.append(imageMode, imageText); box.appendChild(imageForm);
    function saveImageDraft() {
      imageDrafts[currentRow] = {mode: imageMode.value, text: imageText.value};
    }
    imageText.addEventListener('input', saveImageDraft); imageMode.addEventListener('change', saveImageDraft);
    var reprompt = make('form', 'pav-reprompt'); reprompt.hidden = true;
    var directionLabel = make('label', '', 'Direction'), direction = make('textarea');
    direction.rows = 3; direction.maxLength = 1800; direction.required = true; directionLabel.appendChild(direction);
    var speechLabel = make('label', '', 'Dialogue'), speech = make('textarea'); speech.rows = 2; speech.maxLength = 800; speechLabel.appendChild(speech);
    var submit = make('button', '', 'Send to H3'); submit.type = 'submit';
    reprompt.append(directionLabel, speechLabel, submit); box.appendChild(reprompt);
    var status = make('p', 'pav-status'); status.setAttribute('role', 'status'); box.appendChild(status);
    var actions = make('footer', 'pine-voice-ad-actions');
    var save = command('Save to PineBoxRecordings', 'c:save', saveCurrent);
    var splice = make('button', 'pav-splice', 'Splice'); splice.type = 'button';
    splice.title = 'Edit the generated and original videos together';
    splice.disabled = true;
    splice.addEventListener('click', function () {
      var row = rows[index];
      if (!row || !row.prompt_id || splice.disabled || splicePending) return;
      var current = revision; splicePending = true;
      splice.disabled = true; status.textContent = 'Preparing both videos for the splice editor...';
      root.pineDesktop.post('/api/video-editor/parody/open', {prompt_id: row.prompt_id, file: mediaFile(row)}).then(function (got) {
        if (gone || current !== revision) return;
        if (!got || !got.original_source_id || !got.generated_source_id) throw new Error('The station did not return both editor sources.');
        if (!root.PineHotCorners || typeof root.PineHotCorners.videoEditor !== 'function') throw new Error('The splice editor is unavailable on this build.');
        root.PineHotCorners.videoEditor(got.original_source_id, got.generated_source_id);
        close();
      }).catch(function (err) {
        if (!gone && current === revision) { status.textContent = 'Could not open Splice: ' + ((err && err.message) || err); splice.disabled = false; }
      }).finally(function () { splicePending = false; });
    });
    save.disabled = true;
    actions.appendChild(save); actions.appendChild(splice);
    var promptAgain = make('button', 'pav-reprompt-button', 'Prompt original again');
    promptAgain.type = 'button'; promptAgain.title = 'Send the recorded original through H3 with a new direction';
    promptAgain.addEventListener('click', function () {
      if (!imageForm.hidden) { renderImage(); return; }
      reprompt.hidden = !reprompt.hidden; promptAgain.setAttribute('aria-expanded', String(!reprompt.hidden));
      if (!reprompt.hidden) { direction.focus(); reprompt.scrollIntoView({block:'nearest'}); }
    });
    promptAgain.disabled = true; promptAgain.setAttribute('aria-expanded', 'false'); actions.appendChild(promptAgain);
    function renderImage() {
      var row = rows[index], file = mediaFile(row), key = currentRow, current = revision;
      var words = imageText.value.trim();
      if (!words) { imageText.focus(); return; }
      if (!row || !file || imageJobs[key]) return;
      imageJobs[key] = true; promptAgain.disabled = true; status.textContent = 'Queuing image stinger...';
      var dialogue = imageMode.value === 'dialogue';
      var body = {mode: 'reference', purpose: 'parody_stinger', source: file, source_type: 'gallery',
        prompt: dialogue ? 'Create a Pine Box FM stinger using the supplied image. Natural motion and synchronized spoken dialogue. No captions or logos.' : words,
        speech: dialogue ? words : '', duration_mode: 'at_least', steps: 4, air_it: false,
        source_generation: row.prompt_id, variant_of: row.prompt_id};
      root.pineDesktop.post('/api/comfy/workshop', body).then(function (got) {
        if (gone || current !== revision) return;
        if (!got || !(got.queue_id || got.prompt_id)) throw new Error('No H3 job was confirmed.');
        status.textContent = 'Image stinger queued for H3. The image is unchanged.';
      }).catch(function (err) {
        if (!gone && current === revision) status.textContent = 'Could not submit: ' + err.message;
      }).finally(function () {
        delete imageJobs[key];
        if (!gone && currentRow === key) promptAgain.disabled = false;
      });
    }
    reprompt.addEventListener('submit', function (event) {
      event.preventDefault();
      var row = rows[index], ref = row && references[row.prompt_id], current = revision;
      if (!ref || !ref.available || ref.kind !== 'video') return;
      var words = direction.value.trim(), dialogue = speech.value.trim();
      if (!words) { direction.focus(); return; }
      submit.disabled = true; status.textContent = 'Queuing a new take from the original...';
      var body = {mode:'reference',purpose:'parody_stinger',source:ref.id,source_type:ref.source_type,
        prompt:words + (dialogue ? '\nSpoken dialogue: ' + dialogue : ''),speech:dialogue,steps:row.steps || 4,
        frames:row.frames || 121,air_it:false,source_generation:row.source_generation || '',variant_of:row.prompt_id};
      ['trim_in_s','trim_out_s','at_share'].forEach(function (key) { if (typeof row[key] === 'number') body[key] = row[key]; });
      root.pineDesktop.post('/api/comfy/workshop', body).then(function (got) {
        if (gone || current !== revision) return;
        status.textContent = got && (got.queue_id || got.prompt_id) ? 'New take submitted to H3. The original is unchanged.' : 'No H3 job was confirmed.';
      }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Could not submit: ' + err.message; })
        .finally(function () { if (!gone && current === revision) submit.disabled = false; });
    });
    var external = make('a', 'pine-voice-ad-open', 'Open media'); external.target = '_blank'; external.rel = 'noopener';
    actions.appendChild(external); actions.appendChild(command('Close ad viewer', 'c:close--filled', close)); box.appendChild(actions);
    veil.appendChild(box); document.body.appendChild(veil);
    if (window.pineCloseX) { window.pineCloseX(box, function () { close(); }, {label: 'Close the ad viewer'}); }  // [closex:ad-viewer]
    if (gallery && root.PineDuck && typeof root.PineDuck.hold === 'function') {
      duckApi = root.PineDuck;
      duckApi.hold('pine-box-gallery', 0.05, veil);
    }
    veil.addEventListener('click', function (e) { if (e.target === veil) close(); });
    var focusWas = document.activeElement;
    function keys(e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (gallery && !pScreen.hidden) showPrompts(false); else close(); }   /* [h3-prompts] the screen first */
      if (e.key === 'Tab') {
        var controls = Array.from(box.querySelectorAll('button:not(:disabled),a[href],textarea,input:not(:disabled),select:not(:disabled)')).filter(function (n) { return n.getClientRects().length; });
        var at = controls.indexOf(document.activeElement);
        if (controls.length && (at < 0 || (e.shiftKey ? at === 0 : at === controls.length - 1))) {
          e.preventDefault(); controls[e.shiftKey ? controls.length - 1 : 0].focus();
        }
      }
    }
    document.addEventListener('keydown', keys, true);
    function close() {
      gone = true; revision++; clearInterval(crawl); clearInterval(h3Timer);
      clearInterval(pTimer); pBackOff();                               /* [h3-prompts] */
      clearTimeout(exportTimer);
      if (rollTag) { try { rollTag.dispose(); } catch (e) { /* gone */ } rollTag = null; }   /* [ad-roll] */
      var rollPop = document.getElementById('pavRollPop'); if (rollPop) rollPop.remove();
      /* [vcrfx: the video goes off the way it came on] */
      var vcrMedia = stage.querySelector('video.pav-media');
      if (root.PineVcr && vcrMedia && vcrMedia.style.visibility === 'visible' && vcrMedia.isConnected) {
        var vcrDispose = disposeMedia;
        disposeMedia = function () {};
        try { vcrMedia.pause(); } catch (e) { /* it stops with the veil */ }
        root.PineVcr.out(vcrMedia).then(function () { vcrDispose(); veil.remove(); });
      } else { disposeMedia(); veil.remove(); }
      if (duckApi && typeof duckApi.release === 'function') duckApi.release('pine-box-gallery');
      duckApi = null;
      if (posterObserver) posterObserver.disconnect(); posterQueue = [];
      document.removeEventListener('keydown', keys, true); opened = null;
      if (focusWas && focusWas.isConnected) focusWas.focus();
    }
    opened = close;
    function sourceUrl(file, thumb) {
      var url = '/api/generations/' + (thumb ? 'image/' : 'media/') + encodeURIComponent(file)
        + '?t=' + encodeURIComponent(signatures[file] || '') + (thumb ? '&w=160' : '');
      return typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(url)
        : (/^https?:$/.test(location.protocol) ? url : 'http://127.0.0.1:8096' + url);
    }
    function paintStrip(keepScroll) {
      if (!gallery || gone) return;
      var old = strip.scrollLeft;
      if (posterObserver) posterObserver.disconnect(); posterQueue = [];
      if (root.IntersectionObserver) posterObserver = new root.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          posterObserver.unobserve(entry.target);
          posterQueue.push({image:entry.target, file:entry.target.dataset.file});
        });
        pumpPosters();
      }, {root:strip, rootMargin:'160px'});
      strip.replaceChildren();
      rows.slice(stripStart, stripStart + 80).forEach(function (row, offset) {
        var at = stripStart + offset, file = mediaFile(row);
        var tile = make('button', 'pav-tile'); tile.type = 'button'; tile.title = file;
        tile.setAttribute('aria-label', file); tile.setAttribute('aria-pressed', String(at === index));
        var thumb = make('img'); thumb.alt = ''; thumb.loading = 'lazy';
        var photo = (row.files || []).find(function (f) { return /\.(png|jpe?g|webp|gif)$/i.test(f); });
        thumb.src = photo ? sourceUrl(photo, true) : posters[file] || root.__pineLogo;
        thumb.onerror = function () { thumb.onerror = null; thumb.src = root.__pineLogo; };
        tile.appendChild(thumb); tile.appendChild(make('span', '', /\.(mp4|webm|mov|m4v)$/i.test(file) ? 'Video' : 'Image'));
        tile.addEventListener('click', function () { index = at; pausedUntil = Date.now() + 5000; paint(true); });
        strip.appendChild(tile);
        if (!photo && !posters[file]) {
          thumb.dataset.file = file;
          if (posterObserver) posterObserver.observe(thumb);
          else posterQueue.push({image:thumb,file:file});
        }
      });
      strip.scrollLeft = keepScroll ? old : 0;
      pumpPosters();
    }
    function loadPage(count) {
      if (loading || gone) return Promise.resolve();
      count = count || 30; loading = true; more.disabled = true;
      var requestPage = pendingRows.length >= count || (rows.length && !cursor) ? Promise.resolve(null) : root.pineDesktop.get('/api/generations/history?limit=' + count + '&purpose=' + (gallery ? '' : 'voice_ad')
        + '&before=' + encodeURIComponent(cursor));
      return requestPage.then(function (payload) {
        if (gone) return;
        loadFailed = false;
        if (payload) { Object.assign(signatures, payload.sig || {}); cursor = payload.next || ''; }
        (payload && payload.generations || []).forEach(function (row) {
          var files = gallery ? (row.files || []).filter(function (f) { return /\.(mp4|webm|mov|m4v|png|jpe?g|webp|gif)$/i.test(f); }) : [mediaFile(row)];
          files.filter(Boolean).forEach(function (file) {
            if (!rows.concat(pendingRows).some(function (r) { return r.prompt_id === row.prompt_id && mediaFile(r) === file; })) pendingRows.push(Object.assign({},row,{files:[file]}));
          });
        });
        rows.push.apply(rows, pendingRows.splice(0, count));
        previous.disabled = index + 1 >= rows.length && !cursor && !pendingRows.length;
        position.textContent = (rows.length - index) + ' / ' + rows.length;
        paintStrip(true);
      }).catch(function (err) {
        loadFailed = true; status.textContent = 'Could not load gallery history: ' + err.message;
      }).finally(function () { loading = false; more.disabled = !cursor && !pendingRows.length; });
    }
    function watchExport(id, current) {
      exportTimer = setTimeout(function () {
        if (gone || current !== revision) return;
        root.pineDesktop.get('/api/export/courier/status/' + encodeURIComponent(id)).then(function (got) {
          if (gone || current !== revision) return;
          status.textContent = got.state === 'delivered' ? 'Saved to ' + got.destination
            : got.state === 'failed' ? 'Archive copy failed: ' + (got.why || 'destination unavailable')
              : 'Archive copy queued; waiting for the desktop courier.';
          if (got.state === 'pending') watchExport(id, current);
        }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Copy status unavailable: ' + err.message; });
      }, 2500);
    }
    function saveCurrent() {
      var row = rows[index], file = mediaFile(row), current = revision;
      if (!file) return;
      save.disabled = true; status.textContent = 'Preparing archive copy...';
      root.pineDesktop.post('/api/gallery/export', {prompt_id: row.prompt_id, file: file,
        scope: original ? 'original' : 'generated', destination: 'share', name: (original ? 'Original-' : '') + file.replace(/\.[^.]+$/, '')}).then(function (got) {
        if (gone || current !== revision) return;
        if (!got || !got.ok || !got.id) throw new Error('The archive copy was not confirmed');
        status.textContent = 'Archive copy queued for ' + got.destination;
        watchExport(got.id, current);
      }).catch(function (err) { if (!gone && current === revision) status.textContent = 'Could not save: ' + err.message; })
        .finally(function () { if (!gone && current === revision) save.disabled = false; });
    }
    function paint(fromStrip) {
      var current = ++revision;
      disposeMedia(); disposeMedia = function () {}; clearTimeout(exportTimer); stage.replaceChildren();
      var row = rows[index], file = mediaFile(row), scene = null, frame = 0, timer = 0;
      var generatedVideo = /\.(mp4|webm|mov|m4v)$/i.test(file || '');
      var rowKey = row.prompt_id + ':' + file;
      if (currentRow !== rowKey) {
        currentRow = rowKey; original = false; reprompt.hidden = true; promptAgain.setAttribute('aria-expanded','false');
        direction.value = String(row.tags || row.request || '').slice(0,1800); speech.value = row.speech || ''; submit.disabled = false;
        var draft = imageDrafts[rowKey] || {mode: 'prompt', text: ''};
        imageMode.value = draft.mode; imageText.value = draft.text;
      }
      imageForm.hidden = generatedVideo || !file;
      promptAgain.textContent = generatedVideo ? 'Prompt original again' : 'Render H3 video';
      promptAgain.title = generatedVideo ? 'Send the recorded original through H3 with a new direction' : 'Render this image as an H3 stinger';
      var reference = references[row.prompt_id];
      generatedButton.setAttribute('aria-pressed', String(!original)); originalButton.setAttribute('aria-pressed', String(original));
      originalButton.disabled = !reference || !reference.available;
      promptAgain.disabled = generatedVideo ? !reference || !reference.available || reference.kind !== 'video' : !file || !!imageJobs[rowKey];
      splice.disabled = !generatedVideo || !reference || !reference.available || reference.kind !== 'video';
      originalButton.title = reference && !reference.available ? reference.reason || 'Original unavailable' : 'Original reference';
      if (!reference) root.pineDesktop.get('/api/comfy/workshop/reference/' + encodeURIComponent(row.prompt_id)).then(function (got) {
        references[row.prompt_id] = got;
        if (gone || current !== revision) return;
        originalButton.disabled = !got.available;
        if (generatedVideo) promptAgain.disabled = !got.available || got.kind !== 'video';
        splice.disabled = !generatedVideo || !got.available || got.kind !== 'video';
        originalButton.title = got.available ? 'Original reference' : got.reason || 'Original unavailable';
      }).catch(function (err) { if (!gone && current === revision) originalButton.title = 'Reference lookup failed: ' + err.message; });
      if (gallery && !fromStrip && (index < stripStart || index >= stripStart + 80)) stripStart = Math.max(0, index - 10);
      paintStrip(!!fromStrip);
      previous.disabled = index + 1 >= rows.length && !cursor && !pendingRows.length; next.disabled = index === 0;
      position.textContent = (rows.length - index) + ' / ' + rows.length;
      description.textContent = String(row.request || row.tags || 'Pine Box ad');
      paintUsed(row);                                                  /* [h3-prompts] the words it was told */
      save.disabled = !file || !signatures[file]; status.textContent = '';
      if (!file) { splice.disabled = true; status.textContent = 'This ad has no playable output file.'; external.removeAttribute('href'); return; }
      var base = sourceUrl(file, false);
      if (original && reference && reference.available) base = typeof root.desktopMusicUrl === 'function' ? root.desktopMusicUrl(reference.url) : reference.url;
      external.href = base;
      var canvas = make('canvas', 'pav-particles'); canvas.setAttribute('aria-hidden', 'true'); stage.appendChild(canvas);
      var play = make('button', 'pav-play'); play.type = 'button'; play.title = 'Play Pine Box ad'; play.setAttribute('aria-label', play.title);
      var logo = make('img', 'pav-logo'); logo.alt = 'Pine Box'; logo.src = root.__pineLogo || '/spark/asset/pinebox.png';
      play.appendChild(logo); stage.appendChild(play);
      var isVideo = original ? reference.kind === 'video' : generatedVideo, media = make(isVideo ? 'video' : 'img', 'pav-media');
      media.style.visibility = 'hidden'; stage.appendChild(media);
      var waiting = true;
      function background(on) {
        waiting = on; canvas.hidden = !on; play.hidden = !on;
        if (scene) { if (on && !document.hidden) scene.start(); else scene.stop(); }
      }
      function reveal() {
        if (gone || current !== revision) return;
        clearTimeout(timer); media.style.visibility = 'visible'; background(false); status.textContent = '';
        /* [vcrfx: an H3 video comes on like the SFX TV] once per picture */
        if (isVideo && root.PineVcr && !media.__vcrOn) { media.__vcrOn = true; root.PineVcr.in(media); }
      }
      function failed(words) {
        if (gone || current !== revision) return;
        clearTimeout(timer); media.style.visibility = 'hidden'; background(true);
        play.disabled = false; play.title = 'Retry Pine Box ad'; play.setAttribute('aria-label', play.title);
        status.textContent = words;
      }
      function visibility() { if (scene) { if (waiting && !document.hidden) scene.start(); else scene.stop(); } }
      document.addEventListener('visibilitychange', visibility);
      if (root.PinePlexus) root.PinePlexus.create(canvas).then(function (made) {
        if (gone || current !== revision) { made.dispose(); return; }
        scene = made; visibility();
      }).catch(function () { /* The branded poster remains available without WebGL. */ });
      media.addEventListener('error', function () { failed('The ad could not be loaded or decoded. Tap the Pine Box logo to retry.'); });
      if (isVideo) {
        media.controls = true; media.playsInline = true; media.preload = 'auto'; media.poster = logo.src;
        media.addEventListener('loadeddata', function () {
          if (media.readyState >= 2 && media.videoWidth > 0) reveal();
        });
        media.addEventListener('playing', function () {
          if (media.requestVideoFrameCallback) frame = media.requestVideoFrameCallback(reveal);
          else if (media.readyState >= 2 && media.videoWidth > 0) reveal();
        });
        function startMedia() {
          if (!signatures[file]) { failed('Media access is unavailable. Close and reopen this ad to refresh its file link.'); return; }
          status.textContent = 'Loading video...'; play.disabled = true;
          clearTimeout(timer);
          if (!media.getAttribute('src') || media.error) { media.src = base; media.load(); }
          timer = setTimeout(function () { failed('No video frame arrived. Check the media file or tap to retry.'); }, 20000);
          Promise.resolve(media.play()).catch(function (err) {
            if (gone || current !== revision) return;
            if (err.name === 'NotAllowedError') {
              play.disabled = false;
              if (media.readyState >= 2 && media.videoWidth > 0) reveal();
            } else failed('Playback failed: ' + err.message);
          })
            .finally(function () { if (current === revision) play.disabled = false; });
        }
        play.addEventListener('click', startMedia);
        startMedia();
      } else {
        media.alt = 'Generated Pine Box ad'; media.addEventListener('load', reveal); media.src = base;
        play.addEventListener('click', function () { media.src = base; });
      }
      disposeMedia = function () {
        clearTimeout(timer); document.removeEventListener('visibilitychange', visibility);
        if (frame && media.cancelVideoFrameCallback) media.cancelVideoFrameCallback(frame);
        if (isVideo) { media.pause(); media.removeAttribute('src'); media.load(); }
        if (scene) scene.dispose();
      };
    }
    previous.disabled = true; next.disabled = true;
    status.textContent = 'Locating generated ads...';
    loadPage().then(async function () {
      if (gone) return;
      if (initial) {
        while (!gone && !loadFailed && (cursor || pendingRows.length) && !rows.some(function (r) { return r.prompt_id === initial.prompt_id; })) await loadPage();
        if (gone) return;
        index = rows.findIndex(function (r) { return r.prompt_id === initial.prompt_id; });
        if (index < 0) {
          index = 0; previous.disabled = true; next.disabled = true;
          if (!loadFailed) status.textContent = 'This ad is not in the completed media archive. Refresh to check again.';
          return;
        }
      }
      if (rows.length) paint(); else if (!loadFailed) status.textContent = 'No completed media in the gallery yet.';
      if (gallery) motion.focus();
    });
    actions.insertBefore(command('Refresh gallery', 'c:renew', function () {
      if (loading) return;
      cursor = ''; rows = []; pendingRows = []; index = 0; stripStart = 0;
      save.disabled = true;
      loadPage().then(function () { if (!gone && rows.length) paint(); });
    }), external);
    if (gallery) crawl = setInterval(function () {
      if (gone || document.hidden || motion.dataset.paused || Date.now() < pausedUntil || loading || loadFailed) return;
      strip.scrollLeft += 1;
      if (strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 3) {
        if (stripStart + 80 < rows.length) { stripStart += 40; paintStrip(false); }
        else if (cursor || pendingRows.length) loadPage();
        else { stripStart = 0; paintStrip(false); }
      }
    }, 40);
  }
  root.PineAdViewer = {open: open, openGallery: function () { open(null, true); }, close: function () { if (opened) opened(); }, mediaFile: mediaFile,
    usedWords: usedWords,                                              /* [h3-prompts] the words a video was told */
    rollRows: rollRows};                                               /* [ad-roll] what the header's roll plays */
  if (typeof module !== 'undefined') module.exports = root.PineAdViewer;
}(typeof window !== 'undefined' ? window : globalThis));
