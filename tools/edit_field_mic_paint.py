"""[field-mic-paint] The dictation mic is painted by its own text field.

THE ASK (the operator, 2026-09-28): "The microphone icons for text entries are
not integrated with their text field, so they're getting out of sync whenever
I'm scrolling the board. I need them integrated physically into the text boxes
so that way they stay in sync whenever I scroll."

THE CAUSE. talk-dot.js decorated every text field in the document with a
position:fixed <button> in a body-level layer (div.pine-field-mics, z
2147483083) and moved it to field.getBoundingClientRect() on window
scroll/resize/visualViewport events, coalesced to the next animation frame and
gated by an IntersectionObserver. So the mic (1) trailed every scroll by at
least a frame - on the tablet the compositor scrolls long before the main
thread hears of it; (2) did not move at all when the field moved WITHOUT a
scroll or resize - a System 3 category <details> folding, a textarea
drag-resized, rows re-rendered, content growing above it; (3) painted over a
window covering its field (the S3 backdrop is z 2147483000) until a hit-test
pass caught up.

THE CURE, AT THE DECORATOR (one place; every document that loads talk-dot.js:
the desktop chrome and the System 3 window opened in it, the tablet kiosk's
panel and its S3 window). Each field paints its own mic: two background
layers - the Carbon microphone glyph and its hover/pressed plate - at the
right of the field's padding box, inside the right padding the field reserves
(the old +36px). The mic is part of the field's box, so it scrolls, folds,
resizes, re-renders and hides with it with no code running: there is no
layer, no coordinate, nothing to sync. The DOM is not touched - no wrapper,
no sibling: a generic wrapper would break views that walk from the field
(system3.js's add-row Enter does e.target.nextSibling.click(); a parent that
insertBefore(x, field)s would throw). A press on the mic is recognised from
the pointer's place in the field (the painted square, a little larger for a
finger) and consumed at the window in the capture phase: tap toggles, hold
450 ms and release finishes (hold-to-talk) - the button's gestures,
unchanged; the field is not focused and no view handler sees the press. The
dictation road itself (captureNext -> listen -> transcribe -> appendWords
with a bubbling input event) is unchanged. A ResizeObserver only decides
whether a field has room for the mic (plate >= 22px, >= 40px of text room
beside it - so the 3em emoji and 4em number boxes are no longer padded shut)
and the plate's size - never its place. The keyboard road the button's Enter
was is Ctrl+Shift+Space in the field. The telemetry strip beside a dictating
field listens to scroll/resize only while that capture is live. Every
document-level hook is guarded as the old layer's mount was (a document with
no root element must never throw out of the module before PineTalkDot is
exported - the telemetry test loads it that way).
DELETED: the fixed layer, placeMic/placeAll/queuePlace, the
IntersectionObserver gating, the elementFromPoint occlusion probe and the
permanent window scroll/resize/visualViewport listeners.

THE TESTS THAT PINNED THE BUTTON move with it (same assertions, new road):
  tests/test-field-dictation.cjs - the harness presses the field's painted
    mic through the window capture listener instead of a button handler; the
    tap / hold / append / focus assertions are unchanged, plus a press in the
    text reaching the field untouched and the live mark clearing.
  tests/test_inline_field_dictation_2026_09_25.cjs - per-field mics are
    data-pine-mic="on" marks (no layer appended), room for text is the same
    44px padding, the mic hit square replaces the button's left/top px.
  tests/test_pine_segments_2026_09_21.cjs - asserts the shared decorator's
    data-pine-mic mark instead of button.className = 'pine-field-mic'.
  (tests/test_dictation_telemetry_2026_09_25.cjs needs no edit: it failed
  only because the unguarded documentElement hook threw at load.)

FILES (each file keeps its own line endings):
  desktop/renderer/talk-dot.js                    (CRLF)
  app/src/main/assets/pine-views/talk-dot.js      (CRLF, byte-identical twin)
  desktop/renderer/view-chrome.css                (LF)
  app/src/main/assets/pine-views/view-chrome.css  (LF, byte-identical twin)
  tests/test-field-dictation.cjs                  (CRLF in the host tree)
  tests/test_inline_field_dictation_2026_09_25.cjs
  tests/test_pine_segments_2026_09_21.cjs
It reaches the desktop at its next launch (runner cache) and the tablet at
the next kiosk APK build + install. No app.py change and no restart. The
anchors are the whole original decorator/CSS blocks (talk-dot.js md5
abe609299f30f49487bf8b7ecf79c0cc, view-chrome.css md5
98c88a354725f47b62ea78755d301772 at HEAD 713c1b1) and context-bearing
hunks of the three tests; no tools/*.py stores any of this text. --apply
prints each file's md5 after the write; compare against those printed
lines, not against a number copied from elsewhere (the md5 depends on the
file's line endings).

Usage: python tools/edit_field_mic_paint.py [--check|--apply] [repo_root]
--check exits 0 ready / 2 applied / 1 missing (nothing is written unless
every file is ready or applied). --apply is idempotent and atomic per file.
"""
import hashlib
import os
import sys
import tempfile

MARK = "[field-mic-paint]"


JS_OLD = r'''  /* Field dictation follows each field through nested scrolling. Established
   * forms use a fixed overlay; popups may opt into a local inline mount. */
  if (root.document && root.document.addEventListener) {
    var fieldButtons = new Map();
    var fieldLayer = root.document.createElement('div');
    fieldLayer.className = 'pine-field-mics';
    var micBusy = false;
    var micMonitor = 0;
    var finishWhenReady = false;
    var scanQueued = false;
    var placeQueued = false;
    var placeHitTest = false;
    var visibleFields = new Set();
    var fieldObserver = null;
    function nextFrame(job) {
      if (typeof root.requestAnimationFrame === 'function') return root.requestAnimationFrame(job);
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, 0);
      job();
      return 0;
    }
    function afterDelay(job, delay) {
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, delay);
      if (typeof setTimeout === 'function') return setTimeout(job, delay);
      job();
      return 0;
    }
    function cancelDelay(timer) {
      if (typeof root.clearTimeout === 'function') root.clearTimeout(timer);
      else if (typeof clearTimeout === 'function') clearTimeout(timer);
    }
    function textField(node) {
      if (!node || node.disabled || node.readOnly) return false;
      if (node.hasAttribute && node.hasAttribute('data-pine-mic-owned')) return false;
      if (node.tagName === 'TEXTAREA') return true;
      if (node.tagName === 'INPUT') return /^(text|search|url|email|tel|number)$/.test(node.type || 'text');
      return node.isContentEditable === true && !node.parentElement?.isContentEditable;
    }
    function viewport() {
      return root.visualViewport || {width: root.innerWidth, height: root.innerHeight,
        offsetLeft: 0, offsetTop: 0};
    }
    function setMicHidden(button, hidden) {
      if (button.hidden !== hidden) button.hidden = hidden;
    }
    function placeMic(field, button, hitTest) {
      if (!field.isConnected || !textField(field)) { setMicHidden(button, true); return; }
      var rect = field.getBoundingClientRect();
      var view = viewport();
      var size = Math.min(32, Math.max(0, rect.height - 4), Math.max(0, rect.width - 4));
      var inline = button.classList.contains('pine-field-mic-inline');
      var x = rect.right - size - 3;
      var y = rect.top + Math.max(2, (rect.height - size) / 2);
      setMicHidden(button, size < 22 || rect.width < 48 || rect.right <= 0
        || rect.left >= view.width || rect.bottom <= 0 || rect.top >= view.height
        || !!(field.closest && field.closest('[hidden], [aria-hidden="true"]')));
      if (inline) {
        button.style.width = size + 'px';
        button.style.height = size + 'px';
        return;
      }
      /* An elementFromPoint walks the whole document. Do it on first reveal
         and focus, not after every live-feed DOM change. The observer below
         keeps the ordinary placement set to fields that are actually visible. */
      if (hitTest && !button.hidden && root.document.elementFromPoint) {
        button.style.pointerEvents = 'none';
        var hit = root.document.elementFromPoint(
          Math.max(rect.left + 2, Math.min(rect.right - 2, rect.left + rect.width / 2)),
          Math.max(rect.top + 2, Math.min(rect.bottom - 2, rect.top + rect.height / 2)));
        button.style.pointerEvents = '';
        if (hit !== field && !(field.contains && field.contains(hit))) button.hidden = true;
      }
      if (button.hidden) return;
      button.style.width = size + 'px';
      button.style.height = size + 'px';
      button.style.left = x + 'px';
      button.style.top = y + 'px';
    }
    function placeTelemetry() {
      var telemetry = el('pineTalkTelemetry');
      if (!telemetry || !fieldCapture || !fieldCapture.isConnected) return;
      var rect = fieldCapture.getBoundingClientRect();
      var view = viewport();
      var width = Math.min(540, Math.max(230, view.width - 16));
      var belowSpace = Math.max(0, view.height - rect.bottom - 5);
      var aboveSpace = Math.max(0, rect.top - 5);
      var below = belowSpace >= 58 || belowSpace >= aboveSpace;
      var height = Math.min(72, Math.max(50, below ? belowSpace : aboveSpace));
      var top = below ? rect.bottom + 2 : Math.max(2, rect.top - height - 2);
      telemetry.style.left = Math.max(8, Math.min(view.width - width - 8, rect.left)) + 'px';
      telemetry.style.top = top + 'px';
      telemetry.style.width = width + 'px';
      telemetry.style.height = height + 'px';
    }
    function placeAll(hitTest) {
      var fields = fieldObserver ? visibleFields : fieldButtons;
      fields.forEach(function (value, key) {
        var field = fieldObserver ? value : key;
        var button = fieldObserver ? fieldButtons.get(field) : value;
        if (!field || !button || !field.isConnected) {
          if (button) button.remove();
          fieldButtons.delete(field);
          visibleFields.delete(field);
          return;
        }
        placeMic(field, button, hitTest);
      });
      placeTelemetry();
    }
    function queuePlace(hitTest) {
      placeHitTest = placeHitTest || !!hitTest;
      if (placeQueued) return;
      placeQueued = true;
      nextFrame(function () {
        var probe = placeHitTest;
        placeQueued = false;
        placeHitTest = false;
        placeAll(probe);
      });
    }
    function queueScan() {
      if (scanQueued) return;
      scanQueued = true;
      nextFrame(function () { scanQueued = false; scan(); });
    }
    function scan() {
      var fields = root.document.querySelectorAll
        ? root.document.querySelectorAll('input, textarea, [contenteditable="true"]') : [];
      var added = false;
      for (var i = 0; i < fields.length; i += 1) {
        var field = fields[i];
        if (!textField(field) || fieldButtons.has(field)) continue;
        var button = makeMic(field);
        fieldButtons.set(field, button);
        added = true;
        if (fieldObserver) fieldObserver.observe(field);
      }
      if (added && !fieldObserver) queuePlace(true);
    }
    function reserveSpace(field) {
      if (!field.style || !field.style.setProperty) return;
      var style = root.getComputedStyle ? root.getComputedStyle(field) : null;
      var right = style ? parseFloat(style.paddingRight) || 0 : 0;
      field.style.setProperty('padding-right', (right + 36) + 'px', 'important');
    }
    function appendWords(field, words) {
      if (!field || !field.isConnected || !words) return;
      var stillFocused = !root.document || root.document.activeElement === field;
      var old = field.isContentEditable ? field.textContent : field.value;
      var joined = old + (old && !/\s$/.test(old) ? ' ' : '') + words;
      if (field.isContentEditable) field.textContent = joined;
      else field.value = joined;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      if (stillFocused) field.focus();
      if (stillFocused && field.setSelectionRange) field.setSelectionRange(joined.length, joined.length);
    }
    function clearMic() {
      root.clearInterval(micMonitor);
      micMonitor = 0;
      micBusy = false;
      finishWhenReady = false;
      fieldButtons.forEach(function (button) { button.setAttribute('aria-pressed', 'false'); });
      fieldCapture = null;
    }
    function startMic(field, button) {
      if (micBusy || state !== IDLE || !textField(field)) return;
      micBusy = true;
      fieldCapture = field;
      button.setAttribute('aria-pressed', 'true');
      if (root.document && typeof root.document.getElementById === 'function') {
        mount();
        placeTelemetry();
      }
      var started = Date.now();
      root.clearInterval(micMonitor);
      micMonitor = root.setInterval(function () {
        if (Date.now() - started < 3000 || root.PineTalkDot.state() !== IDLE) return;
        clearMic();
      }, 500);
      Promise.resolve(root.PineTalkDot.captureNext(function (words) {
        appendWords(field, String(words || '').trim());
        clearMic();
      })).then(function () {
        if (finishWhenReady) root.PineTalkDot.finish();
      }).catch(clearMic);
    }
    function stopMic() {
      if (!micBusy) return;
      if (root.PineTalkDot.state() === LISTENING) root.PineTalkDot.finish();
      else finishWhenReady = true;
    }
    function makeMic(field) {
      var inlineContainer = field.hasAttribute('data-pine-mic-inline')
        && field.closest && field.closest('[data-pine-mic-container]');
      if (!inlineContainer) reserveSpace(field);
      var button = root.document.createElement('button');
      var pressedAt = 0;
      var wasListening = false;
      var holdTimer = 0;
      var held = false;
      button.type = 'button';
      button.className = 'pine-field-mic';
      if (inlineContainer) button.classList.add('pine-field-mic-inline');
      button.hidden = true;
      button.title = 'Tap to dictate or stop; hold to talk and release to transcribe';
      button.setAttribute('aria-label', button.title);
      button.setAttribute('aria-pressed', 'false');
      button.innerHTML = (typeof root.pineIcon === 'function'
        ? root.pineIcon('c:microphone', 'Dictate') : '') || '&#127908;';
      button.addEventListener('pointerdown', function (event) {
        event.preventDefault();
        pressedAt = Date.now();
        wasListening = micBusy;
        held = false;
        if (micBusy) stopMic(); else startMic(field, button);
        cancelDelay(holdTimer);
        holdTimer = afterDelay(function () {
          holdTimer = 0;
          held = true;
        }, 450);
        try { button.setPointerCapture(event.pointerId); } catch (err) { /* released */ }
      });
      button.addEventListener('pointerup', function () {
        if (holdTimer) cancelDelay(holdTimer);
        holdTimer = 0;
        if (pressedAt && !wasListening && (held || Date.now() - pressedAt >= 450)) stopMic();
        pressedAt = 0;
        held = false;
      });
      button.addEventListener('pointercancel', function () {
        if (holdTimer) cancelDelay(holdTimer);
        holdTimer = 0;
        if (pressedAt && !wasListening) stopMic();
        pressedAt = 0;
        held = false;
      });
      button.addEventListener('click', function (event) {
        if (event.detail !== 0) return;
        if (micBusy) stopMic(); else startMic(field, button);
      });
      if (inlineContainer) inlineContainer.appendChild(button);
      else if (fieldLayer.appendChild) fieldLayer.appendChild(button);
      return button;
    }
    (root.document.body || root.document.documentElement).appendChild(fieldLayer);
    if (typeof root.IntersectionObserver === 'function') {
      fieldObserver = new root.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          var field = entry.target;
          var button = fieldButtons.get(field);
          if (!button) return;
          if (entry.isIntersecting) {
            visibleFields.add(field);
            placeMic(field, button, true);
          } else {
            visibleFields.delete(field);
            setMicHidden(button, true);
          }
        });
        placeTelemetry();
      });
    }
    root.document.addEventListener('focusin', function (event) {
      var field = event.target;
      if (!textField(field)) return;
      var button = fieldButtons.get(field);
      if (!button) {
        button = makeMic(field);
        fieldButtons.set(field, button);
        if (fieldObserver) fieldObserver.observe(field);
      }
      visibleFields.add(field);
      placeMic(field, button, true);
      queueScan();
    });
    root.addEventListener('resize', queuePlace);
    root.addEventListener('scroll', queuePlace, true);
    if (root.visualViewport) {
      root.visualViewport.addEventListener('resize', queuePlace);
      root.visualViewport.addEventListener('scroll', queuePlace);
    }
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i += 1) {
          var nodes = records[i].addedNodes || [];
          for (var j = 0; j < nodes.length; j += 1) {
            var node = nodes[j];
            if (node && node.nodeType === 1 && (textField(node)
                || (node.querySelector && node.querySelector('input, textarea, [contenteditable="true"]')))) {
              queueScan();
              return;
            }
          }
        }
      }).observe(root.document.body || root.document.documentElement,
        {childList: true, subtree: true});
    }
    scan();
  }
'''


JS_NEW = r'''  /* [field-mic-paint] 2026-09-28 THE MIC IS PAINTED BY ITS OWN FIELD.
   * "The microphone icons for text entries are not integrated with their
   * text field, so they're getting out of sync whenever I'm scrolling the
   * board. I need them integrated physically into the text boxes so that
   * way they stay in sync whenever I scroll." (the operator)
   * The mic used to be a position:fixed button in a body-level layer, moved
   * to the field's last known place on each scroll/resize event: it trailed
   * a touch scroll by frames, stayed behind when a fold, a drag-resize or a
   * re-render moved the field without a scroll, and painted over windows
   * that covered its field. Now every text field paints its own mic - two
   * background layers (the Carbon glyph and its hover/pressed plate,
   * view-chrome.css) at the right of the field's padding box, inside the
   * right padding the field reserves - so the mic IS part of the field's
   * box: it scrolls, folds, resizes, re-renders and hides with it, in every
   * pane, at every size, with no code running. The DOM is not touched: no
   * wrapper, no sibling, no layer, so a view's field.nextSibling,
   * parent.insertBefore(x, field), grid placement and child selectors see
   * exactly what the view built (system3.js's add-row Enter clicks
   * e.target.nextSibling - a wrapped field would have clicked the mic).
   * A press on the mic is recognised from the pointer's place inside the
   * field (the square the CSS paints) and is consumed there: the field is
   * not focused, no caret moves, no view handler sees it. The only observer
   * left decides WHETHER a field has room for the mic and how big the plate
   * is - never where it is. */
  if (root.document && root.document.addEventListener) {
    var MIC_RESERVE = 36;      /* right padding a mic takes: plate 32 + gaps */
    var MIC_GAP = 2;           /* padding-box right edge to the plate */
    var MIC_ROOM = 40;         /* text room a field keeps beside its mic */
    var micState = new WeakMap();
    var micFields = new Set();
    var micBusy = false;
    var micMonitor = 0;
    var finishWhenReady = false;
    var scanQueued = false;
    var sweepQueued = false;
    var liveField = null;
    var hoverField = null;
    var press = null;
    var swallow = null;
    var telemetryQueued = false;
    var telemetryFollowing = false;
    var refitQueued = false;
    var refitFields = new Set();
    var sizeObserver = typeof root.ResizeObserver === 'function'
      ? new root.ResizeObserver(observed) : null;
    function nextFrame(job) {
      if (typeof root.requestAnimationFrame === 'function') return root.requestAnimationFrame(job);
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, 0);
      job();
      return 0;
    }
    function afterDelay(job, delay) {
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, delay);
      if (typeof setTimeout === 'function') return setTimeout(job, delay);
      job();
      return 0;
    }
    function cancelDelay(timer) {
      if (typeof root.clearTimeout === 'function') root.clearTimeout(timer);
      else if (typeof clearTimeout === 'function') clearTimeout(timer);
    }
    function textField(node) {
      if (!node || node.disabled || node.readOnly) return false;
      if (node.hasAttribute && node.hasAttribute('data-pine-mic-owned')) return false;
      if (node.tagName === 'TEXTAREA') return true;
      if (node.tagName === 'INPUT') return /^(text|search|url|email|tel|number)$/.test(node.type || 'text');
      return node.isContentEditable === true && !node.parentElement?.isContentEditable;
    }
    function viewport() {
      return root.visualViewport || {width: root.innerWidth, height: root.innerHeight,
        offsetLeft: 0, offsetTop: 0};
    }
    /* Whether the field has room for the mic, and the plate's size - the old
       overlay's rule (plate min(32, height - 4); none under 22) plus room for
       text beside it, so a 3em emoji box or a 4em number box is never
       padded shut. The room is measured as it would be WITH the mic, so
       reserving the padding can never flip the answer back. Reads only. */
    function judge(field, st) {
      if (!field.isConnected || !textField(field) || field.clientWidth <= 0) return {on: false, size: 0};
      var size = Math.min(32, field.clientHeight - 2);
      var room = field.clientWidth - st.padLeft - st.padRight - (st.own ? 0 : MIC_RESERVE);
      return {on: size >= 22 && room >= MIC_ROOM, size: size};
    }
    /* Writes only: the reserved padding, the plate size, the on/off mark. */
    function apply(field, st, verdict) {
      if (!st.own && verdict.on && !st.reserved) {
        field.style.setProperty('padding-right', (st.padRight + MIC_RESERVE) + 'px', 'important');
        st.reserved = true;
      } else if (!verdict.on && st.reserved) {
        if (st.inlinePad) field.style.setProperty('padding-right', st.inlinePad, st.inlinePriority);
        else field.style.removeProperty('padding-right');
        st.reserved = false;
      }
      if (verdict.on && st.size !== verdict.size) {
        field.style.setProperty('--pine-mic-size', verdict.size + 'px');
        st.size = verdict.size;
      }
      mark(field, verdict.on);
    }
    function mark(field, on) {
      var value = on ? 'on' : 'off';
      if (field.getAttribute('data-pine-mic') !== value) field.setAttribute('data-pine-mic', value);
      if (!on && hoverField === field) setHover(null);
    }
    /* A field that grew, shrank, appeared or vanished. The plate follows at
       once (paint only); a change that must add or drop the reserved padding
       - a layout change - waits for the next frame, so this observer never
       resizes what it observes (no "ResizeObserver loop" error in any page). */
    function observed(entries) {
      for (var i = 0; i < entries.length; i += 1) {
        var field = entries[i].target;
        var st = micState.get(field);
        if (!st) continue;
        var verdict = judge(field, st);
        if (!st.own && verdict.on !== st.reserved) {
          if (!verdict.on) mark(field, false);
          refitFields.add(field);
          queueRefit();
        } else {
          apply(field, st, verdict);
        }
      }
    }
    function queueRefit() {
      if (refitQueued) return;
      refitQueued = true;
      nextFrame(function () {
        refitQueued = false;
        var list = [];
        refitFields.forEach(function (field) { if (micState.has(field)) list.push(field); });
        refitFields.clear();
        fitAll(list);
      });
    }
    /* Read every field first, then write every field: one layout, however
       many fields a re-render brings. */
    function fitAll(list) {
      var verdicts = [];
      for (var i = 0; i < list.length; i += 1) verdicts.push(judge(list[i], micState.get(list[i])));
      for (var j = 0; j < list.length; j += 1) apply(list[j], micState.get(list[j]), verdicts[j]);
    }
    function adopt(field) {
      var st = micState.get(field);
      if (st) return st;
      var style = root.getComputedStyle ? root.getComputedStyle(field) : null;
      var picture = style ? style.backgroundImage : 'none';
      st = {
        padLeft: style ? parseFloat(style.paddingLeft) || 0 : 0,
        padRight: style ? parseFloat(style.paddingRight) || 0 : 0,
        inlinePad: field.style ? field.style.getPropertyValue('padding-right') : '',
        inlinePriority: field.style ? field.style.getPropertyPriority('padding-right') : '',
        own: field.hasAttribute('data-pine-mic-inline'),
        reserved: false,
        size: 0,
        touch: false,
        layered: false,
        /* a field that paints its own picture keeps it, under the mic */
        layers: picture && picture !== 'none' ? {
          'background-image': picture,
          'background-position': style.getPropertyValue('background-position'),
          'background-size': style.getPropertyValue('background-size'),
          'background-repeat': style.getPropertyValue('background-repeat'),
          'background-origin': style.getPropertyValue('background-origin'),
          'background-attachment': style.getPropertyValue('background-attachment')
        } : null
      };
      micState.set(field, st);
      return st;
    }
    var MIC_LAYERS = {
      'background-image': 'var(--pine-mic-glyph, none), var(--pine-mic-plate, none)',
      'background-position': 'right calc(2px + (var(--pine-mic-size, 32px) - 17px) / 2) center, right 2px center',
      'background-size': '17px 17px, var(--pine-mic-size, 32px) var(--pine-mic-size, 32px)',
      'background-repeat': 'no-repeat, no-repeat',
      'background-origin': 'padding-box, padding-box',
      'background-attachment': 'scroll, scroll'
    };
    function enlist(field, st) {
      if (st.layers && !st.layered && field.style) {
        st.layered = true;
        Object.keys(MIC_LAYERS).forEach(function (name) {
          field.style.setProperty(name, MIC_LAYERS[name] + ', ' + st.layers[name], 'important');
        });
      }
      if (micFields.has(field)) return;
      micFields.add(field);
      /* Touch: a press that starts on the mic must not scroll the pane,
         long-press-select the text or become a tap that focuses the field.
         Only fields carry this non-passive listener, never the document, so
         scrolling anywhere else is never held for the main thread. */
      if (!st.touch) {
        st.touch = true;
        field.addEventListener('touchstart', function (event) {
          if (press && press.field === field) event.preventDefault();
        }, {passive: false});
      }
      if (sizeObserver) sizeObserver.observe(field);
    }
    /* Adopt a batch of fields: read all their styles, then all their boxes,
       then write - a re-render of three hundred rows costs one layout. */
    function decorate(list) {
      var states = [];
      var verdicts = [];
      var i;
      for (i = 0; i < list.length; i += 1) states.push(adopt(list[i]));
      for (i = 0; i < list.length; i += 1) verdicts.push(judge(list[i], states[i]));
      for (i = 0; i < list.length; i += 1) {
        enlist(list[i], states[i]);
        apply(list[i], states[i], verdicts[i]);
      }
    }
    function sweep() {
      sweepQueued = false;
      micFields.forEach(function (field) {
        if (field.isConnected) return;
        micFields.delete(field);
        if (sizeObserver) sizeObserver.unobserve(field);
        if (hoverField === field) setHover(null);
      });
    }
    function queueSweep() {
      if (sweepQueued) return;
      sweepQueued = true;
      nextFrame(sweep);
    }
    function queueScan() {
      if (scanQueued) return;
      scanQueued = true;
      nextFrame(function () { scanQueued = false; scan(); });
    }
    function scan() {
      var fields = root.document.querySelectorAll
        ? root.document.querySelectorAll('input, textarea, [contenteditable="true"]') : [];
      var fresh = [];
      for (var i = 0; i < fields.length; i += 1) {
        if (!micFields.has(fields[i]) && textField(fields[i])) fresh.push(fields[i]);
      }
      if (fresh.length) decorate(fresh);
    }
    /* The square the CSS paints, in the field's own (untransformed) padding
       box, a little larger for a finger. */
    function onMic(field, event) {
      var st = micState.get(field);
      if (!st || field.getAttribute('data-pine-mic') !== 'on' || !textField(field)) return false;
      if (field.closest && field.closest('[aria-hidden="true"]')) return false;
      var rect = field.getBoundingClientRect();
      if (!rect.width || !rect.height || !field.offsetWidth || !field.offsetHeight) return false;
      var x = (event.clientX - rect.left) * field.offsetWidth / rect.width - field.clientLeft;
      var y = (event.clientY - rect.top) * field.offsetHeight / rect.height - field.clientTop;
      var size = st.size || 32;
      var slop = event.pointerType === 'touch' ? 6 : 2;
      var right = field.clientWidth - MIC_GAP;
      var top = (field.clientHeight - size) / 2;
      return x >= right - size - slop && x <= field.clientWidth + slop
        && y >= top - slop && y <= top + size + slop;
    }
    function micField(node) {
      while (node && node.nodeType !== 1) node = node.parentNode;
      var field = node && node.closest ? node.closest('[data-pine-mic="on"]') : null;
      return field && micState.has(field) ? field : null;
    }
    function setHover(field) {
      if (hoverField === field) return;
      if (hoverField) hoverField.removeAttribute('data-pine-mic-hover');
      hoverField = field;
      if (field) field.setAttribute('data-pine-mic-hover', '');
    }
    function setLive(field) {
      if (liveField && liveField !== field) liveField.removeAttribute('data-pine-mic-live');
      liveField = field;
      if (field) field.setAttribute('data-pine-mic-live', '');
    }
    /* The telemetry strip beside a dictating field is a short-lived popup,
       not part of the field: it follows the field only while a capture is
       live, and nothing listens at all the rest of the time. */
    function placeTelemetry() {
      var telemetry = el('pineTalkTelemetry');
      if (!telemetry || !fieldCapture || !fieldCapture.isConnected) return;
      var rect = fieldCapture.getBoundingClientRect();
      var view = viewport();
      var width = Math.min(540, Math.max(230, view.width - 16));
      var belowSpace = Math.max(0, view.height - rect.bottom - 5);
      var aboveSpace = Math.max(0, rect.top - 5);
      var below = belowSpace >= 58 || belowSpace >= aboveSpace;
      var height = Math.min(72, Math.max(50, below ? belowSpace : aboveSpace));
      var top = below ? rect.bottom + 2 : Math.max(2, rect.top - height - 2);
      telemetry.style.left = Math.max(8, Math.min(view.width - width - 8, rect.left)) + 'px';
      telemetry.style.top = top + 'px';
      telemetry.style.width = width + 'px';
      telemetry.style.height = height + 'px';
    }
    function queueTelemetry() {
      if (telemetryQueued || !fieldCapture) return;
      telemetryQueued = true;
      nextFrame(function () { telemetryQueued = false; placeTelemetry(); });
    }
    function followTelemetry(on) {
      if (telemetryFollowing === on) return;
      telemetryFollowing = on;
      var how = on ? 'addEventListener' : 'removeEventListener';
      /* a host without the method simply has no strip to follow - finishing
         a capture must never throw here, or appendWords' caller skips the
         rest of clearMic */
      [[root, true], [root.visualViewport, false]].forEach(function (pair) {
        var target = pair[0];
        if (!target || typeof target[how] !== 'function') return;
        target[how]('resize', queueTelemetry);
        target[how]('scroll', queueTelemetry, pair[1]);
      });
    }
    function appendWords(field, words) {
      if (!field || !field.isConnected || !words) return;
      var stillFocused = !root.document || root.document.activeElement === field;
      var old = field.isContentEditable ? field.textContent : field.value;
      var joined = old + (old && !/\s$/.test(old) ? ' ' : '') + words;
      if (field.isContentEditable) field.textContent = joined;
      else field.value = joined;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      if (stillFocused) field.focus();
      if (stillFocused && field.setSelectionRange) field.setSelectionRange(joined.length, joined.length);
    }
    function clearMic() {
      root.clearInterval(micMonitor);
      micMonitor = 0;
      micBusy = false;
      finishWhenReady = false;
      setLive(null);
      followTelemetry(false);
      fieldCapture = null;
    }
    function startMic(field) {
      if (micBusy || state !== IDLE || !textField(field)) return;
      micBusy = true;
      fieldCapture = field;
      setLive(field);
      if (root.document && typeof root.document.getElementById === 'function') {
        mount();
        placeTelemetry();
        followTelemetry(true);
      }
      var started = Date.now();
      root.clearInterval(micMonitor);
      micMonitor = root.setInterval(function () {
        if (Date.now() - started < 3000 || root.PineTalkDot.state() !== IDLE) return;
        clearMic();
      }, 500);
      Promise.resolve(root.PineTalkDot.captureNext(function (words) {
        appendWords(field, String(words || '').trim());
        clearMic();
      })).then(function () {
        if (finishWhenReady) root.PineTalkDot.finish();
      }).catch(clearMic);
    }
    function stopMic() {
      if (!micBusy) return;
      if (root.PineTalkDot.state() === LISTENING) root.PineTalkDot.finish();
      else finishWhenReady = true;
    }
    /* Tap toggles; hold 450 ms and release to finish (hold-to-talk) - the
       button's gestures, unchanged, now read off the field's own mic. The
       press is consumed before any view listener runs (window, capture). */
    function swallowPress(event) {
      event.preventDefault();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      else event.stopPropagation();
    }
    root.addEventListener('pointerdown', function (event) {
      if (event.button > 0) return;
      var field = micField(event.target);
      if (!field || !onMic(field, event)) return;
      swallowPress(event);
      if (press) cancelDelay(press.timer);
      press = {field: field, id: event.pointerId, at: Date.now(), was: micBusy, held: false, timer: 0};
      if (micBusy) stopMic(); else startMic(field);
      var mine = press;
      mine.timer = afterDelay(function () { mine.timer = 0; mine.held = true; }, 450);
      try { field.setPointerCapture(event.pointerId); } catch (err) { /* released */ }
    }, true);
    function endPress(event, cancelled) {
      if (!press || (event.pointerId !== undefined && event.pointerId !== press.id)) return;
      swallowPress(event);
      if (press.timer) cancelDelay(press.timer);
      if (!press.was && (cancelled || press.held || Date.now() - press.at >= 450)) stopMic();
      swallow = {field: press.field, until: Date.now() + 350};
      press = null;
    }
    root.addEventListener('pointerup', function (event) { endPress(event, false); }, true);
    root.addEventListener('pointercancel', function (event) { endPress(event, true); }, true);
    /* The rest of the press - mouse compatibility events, the click, a
       long-press menu - belongs to the mic, not to the field or the view. */
    ['mousedown', 'mouseup', 'click', 'dblclick', 'contextmenu'].forEach(function (name) {
      root.addEventListener(name, function (event) {
        var owner = press ? press.field
          : swallow && Date.now() <= swallow.until ? swallow.field : null;
        if (!press && swallow && !owner) swallow = null;
        var target = event.target;
        if (!owner || (target !== owner && !(owner.contains && owner.contains(target)))) return;
        swallowPress(event);
        if (name === 'click' && !press) swallow = null;
      }, true);
    });
    root.addEventListener('pointermove', function (event) {
      if (event.pointerType === 'touch') return;
      var field = micField(event.target);
      setHover(field && onMic(field, event) ? field : null);
    }, {capture: true, passive: true});
    /* Guarded as the old layer's mount was: a document with no root element
       yet (a bare harness, an early or torn-down document) must never throw
       out of this block, or PineTalkDot is never exported. */
    var micRoot = root.document.documentElement || root.document.body;
    if (micRoot && typeof micRoot.addEventListener === 'function') {
      micRoot.addEventListener('pointerleave', function () { setHover(null); });
    }
    /* The keyboard road the button's Enter used to be: Ctrl+Shift+Space in
       a field with a mic taps it. */
    root.document.addEventListener('keydown', function (event) {
      if (!event.ctrlKey || !event.shiftKey || event.altKey || event.metaKey) return;
      if (event.code !== 'Space' && event.key !== ' ') return;
      var field = micField(event.target);
      if (!field) return;
      event.preventDefault();
      if (micBusy) stopMic(); else startMic(field);
    }, true);
    root.document.addEventListener('focusin', function (event) {
      var field = event.target;
      if (textField(field) && !micFields.has(field)) decorate([field]);
      queueScan();
    });
    if (typeof MutationObserver !== 'undefined' && (root.document.body || micRoot)) {
      new MutationObserver(function (records) {
        var scanNeeded = false;
        var sweepNeeded = false;
        for (var i = 0; i < records.length; i += 1) {
          var nodes = records[i].addedNodes || [];
          for (var j = 0; j < nodes.length && !scanNeeded; j += 1) {
            var node = nodes[j];
            if (node && node.nodeType === 1 && (textField(node)
                || (node.querySelector && node.querySelector('input, textarea, [contenteditable="true"]')))) {
              scanNeeded = true;
            }
          }
          if (!sweepNeeded && records[i].removedNodes && records[i].removedNodes.length) sweepNeeded = true;
        }
        if (scanNeeded) queueScan();
        if (sweepNeeded && micFields.size) queueSweep();
      }).observe(root.document.body || micRoot,
        {childList: true, subtree: true});
    }
    scan();
  }
'''


CSS_OLD = r'''.pine-field-mics {
  position: fixed;
  inset: 0;
  z-index: 2147483083;
  pointer-events: none;
}
.pine-field-mic {
  position: fixed;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #8fcbd2;
  cursor: pointer;
  pointer-events: auto;
}
.pine-field-mic[hidden] { display: none; }
.pine-field-mic svg { width: 17px; height: 17px; }
.pine-field-mic:hover, .pine-field-mic:focus-visible,
.pine-field-mic[aria-pressed="true"] { color: #c4f4f3; background: #24424a; }
.pine-field-mic[aria-pressed="true"] { box-shadow: inset 0 0 0 1px #65c7da; }
'''


CSS_NEW = r'''/* [field-mic-paint] THE MIC IS PAINTED BY ITS FIELD (talk-dot.js). Every
   text field that can take dictation wears data-pine-mic="on" and paints the
   mic itself: the Carbon glyph (17px) over its plate (32px, or the field's
   height - 4 when shorter), at the right of its padding box, in the right
   padding the field reserves. Being the field's own background it scrolls,
   folds, resizes and hides with the field - there is no layer to sync.
   The colours are the old button's: idle #8fcbd2 on nothing; hover and
   pressed #c4f4f3 on #24424a; pressed adds the 1px #65c7da ring. */
:root {
  --pine-mic-glyph-idle: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='%238fcbd2'%3E%3Cpath d='M23,14v3A7,7,0,0,1,9,17V14H7v3a9,9,0,0,0,8,8.94V28H11v2H21V28H17V25.94A9,9,0,0,0,25,17V14Z'/%3E%3Cpath d='M16,22a5,5,0,0,0,5-5V7A5,5,0,0,0,11,7V17A5,5,0,0,0,16,22ZM13,7a3,3,0,0,1,6,0V17a3,3,0,0,1-6,0Z'/%3E%3C/svg%3E");
  --pine-mic-glyph-hot: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='%23c4f4f3'%3E%3Cpath d='M23,14v3A7,7,0,0,1,9,17V14H7v3a9,9,0,0,0,8,8.94V28H11v2H21V28H17V25.94A9,9,0,0,0,25,17V14Z'/%3E%3Cpath d='M16,22a5,5,0,0,0,5-5V7A5,5,0,0,0,11,7V17A5,5,0,0,0,16,22ZM13,7a3,3,0,0,1,6,0V17a3,3,0,0,1-6,0Z'/%3E%3C/svg%3E");
  --pine-mic-plate-hot: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Crect width='100%25' height='100%25' rx='3' fill='%2324424a'/%3E%3C/svg%3E");
  --pine-mic-plate-live: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Crect width='100%25' height='100%25' rx='3' fill='%2324424a' stroke='%2365c7da' stroke-width='2'/%3E%3C/svg%3E");
}
[data-pine-mic="on"] {
  --pine-mic-glyph: var(--pine-mic-glyph-idle);
  --pine-mic-plate: none;
  background-image: var(--pine-mic-glyph), var(--pine-mic-plate) !important;
  background-position: right calc(2px + (var(--pine-mic-size, 32px) - 17px) / 2) center, right 2px center !important;
  background-size: 17px 17px, var(--pine-mic-size, 32px) var(--pine-mic-size, 32px) !important;
  background-repeat: no-repeat !important;
  background-origin: padding-box !important;
  background-attachment: scroll !important;
}
[data-pine-mic="on"][data-pine-mic-hover] {
  --pine-mic-glyph: var(--pine-mic-glyph-hot);
  --pine-mic-plate: var(--pine-mic-plate-hot);
  cursor: pointer !important;
}
[data-pine-mic="on"][data-pine-mic-live] {
  --pine-mic-glyph: var(--pine-mic-glyph-hot);
  --pine-mic-plate: var(--pine-mic-plate-live);
}
[data-pine-mic="on"]:read-only,
[aria-hidden="true"] [data-pine-mic="on"],
[data-pine-mic="on"][aria-hidden="true"] {
  --pine-mic-glyph: none;
  --pine-mic-plate: none;
  cursor: auto !important;
}
'''


TEST_1 = [  # tests/test-field-dictation.cjs


    (r'''const source = fs.readFileSync(path.join(__dirname, '../app/src/main/assets/pine-views/talk-dot.js'), 'utf8');

function harness() {
  const timers = new Map();
  let timerId = 0;
  const docHandlers = {};
  const buttonHandlers = {};
  const doc = {
    activeElement: null,
    addEventListener(type, fn) { docHandlers[type] = fn; },
    createElement() {
      return {
        style: {}, isConnected: true,
        classList: {contains() { return false; }},
        setAttribute() {},
        addEventListener(type, fn) { buttonHandlers[type] = fn; },
        setPointerCapture() {},
      };
    },
    body: {appendChild(button) { this.button = button; }},
  };
  class Input {
''',
     r'''const source = fs.readFileSync(path.join(__dirname, '../app/src/main/assets/pine-views/talk-dot.js'), 'utf8');

/* [field-mic-paint] The mic is painted by the field itself (talk-dot.js):
 * there is no button to press. A press is a real pointer event at the window,
 * in the capture phase, at the square the field paints at its right edge
 * (inside its padding box); a press anywhere else in the field is the
 * field's own. The assertions below are the button-era ones, unchanged. */
function harness() {
  const timers = new Map();
  let timerId = 0;
  const docHandlers = {};
  const winHandlers = {};
  const doc = {
    activeElement: null,
    addEventListener(type, fn) { docHandlers[type] = fn; },
    createElement() { return {style: {}, setAttribute() {}, addEventListener() {}}; },
    body: {appendChild() {}},
  };
  class Input {
'''),


    (r'''      this.tagName = 'INPUT';
      this.type = 'text';
      this.isConnected = true;
      this.nativeSets = 0;
      this.events = [];
      this.current = '';
    }
    get value() { return this.current; }
    hasAttribute() { return false; }
    set value(next) { this.nativeSets++; this.current = next; }
    getBoundingClientRect() { return {top: 20, right: 300, bottom: 60}; }
    dispatchEvent(event) { this.events.push(event.type); }
    focus() { doc.activeElement = this; }
''',
     r'''      this.tagName = 'INPUT';
      this.type = 'text';
      this.nodeType = 1;
      this.isConnected = true;
      this.nativeSets = 0;
      this.events = [];
      this.current = '';
      this.attrs = {};
      this.padding = '';
      /* a 280 x 40 box with a 2px border at (20, 20) */
      this.offsetWidth = 280; this.offsetHeight = 40;
      this.clientLeft = 2; this.clientTop = 2;
      this.clientWidth = 276; this.clientHeight = 36;
      const self = this;
      this.style = {
        setProperty(name, value) { if (name === 'padding-right') self.padding = value; },
        removeProperty() {}, getPropertyValue() { return ''; }, getPropertyPriority() { return ''; },
      };
    }
    get value() { return this.current; }
    hasAttribute(name) { return name in this.attrs; }
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    removeAttribute(name) { delete this.attrs[name]; }
    closest(selector) {
      return selector === '[data-pine-mic="on"]' && this.attrs['data-pine-mic'] === 'on' ? this : null;
    }
    addEventListener() {}
    setPointerCapture() {}
    set value(next) { this.nativeSets++; this.current = next; }
    getBoundingClientRect() { return {left: 20, top: 20, right: 300, bottom: 60, width: 280, height: 40}; }
    dispatchEvent(event) { this.events.push(event.type); }
    focus() { doc.activeElement = this; }
'''),


    (r'''    innerWidth: 800,
    innerHeight: 600,
    addEventListener() {},
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
''',
     r'''    innerWidth: 800,
    innerHeight: 600,
    addEventListener(type, fn) { winHandlers[type] = fn; },
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
'''),


    (r'''  let stops = 0;
  let state = 'idle';
  root.PineTalkDot.captureNext = fn => { capture = fn; starts++; state = 'listening'; return Promise.resolve(); };
  root.PineTalkDot.finish = () => { stops++; state = 'idle'; };
''',
     r'''  let stops = 0;
  let state = 'idle';
  let swallowed = 0;
  root.PineTalkDot.captureNext = fn => { capture = fn; starts++; state = 'listening'; return Promise.resolve(); };
  root.PineTalkDot.finish = () => { stops++; state = 'idle'; };
'''),


    (r'''  input.focus();
  docHandlers.focusin({target: input});
  function down() { buttonHandlers.pointerdown({pointerId: 1, preventDefault() {}}); }
  function up() { buttonHandlers.pointerup({}); }
  function fireHold() { for (const fn of timers.values()) fn(); timers.clear(); }
  return {input, doc, Input, down, up, fireHold, say: words => capture(words),
    get starts() { return starts; }, get stops() { return stops; }};
}

''',
     r'''  input.focus();
  docHandlers.focusin({target: input});
  const pointer = (x, y) => ({pointerId: 1, button: 0, pointerType: 'mouse', clientX: x, clientY: y,
    target: input, preventDefault() { swallowed++; }, stopImmediatePropagation() {}});
  /* the painted square: 32px, 2px in from the padding box's right edge,
     centred - its middle is (20 + 2 + 276 - 2 - 16, 20 + 2 + 18) */
  function downAt(x, y) { winHandlers.pointerdown(pointer(x, y)); }
  function down() { downAt(280, 40); }
  function up() { winHandlers.pointerup(pointer(280, 40)); }
  function fireHold() { for (const fn of timers.values()) fn(); timers.clear(); }
  return {input, doc, Input, down, downAt, up, fireHold, say: words => capture(words),
    get starts() { return starts; }, get stops() { return stops; },
    get swallowed() { return swallowed; }};
}

'''),


    (r'''assert.equal(moved.doc.activeElement, other, 'transcript does not steal focus from another field');

console.log('field dictation: tap, hold, append, focus passed');
''',
     r'''assert.equal(moved.doc.activeElement, other, 'transcript does not steal focus from another field');

const paint = harness();
assert.equal(paint.input.getAttribute('data-pine-mic'), 'on', 'the field wears its own mic');
assert.equal(paint.input.padding, '36px', 'text makes room for the painted mic');
paint.downAt(100, 40);
assert.equal(paint.starts, 0, 'a press in the text belongs to the field');
assert.equal(paint.swallowed, 0, 'and reaches it untouched');
paint.down();
assert.equal(paint.starts, 1, 'a press on the painted mic starts capture');
assert.equal(paint.input.hasAttribute('data-pine-mic-live'), true, 'the live mic is marked on the field');
paint.up();
paint.say('painted');
assert.equal(paint.input.hasAttribute('data-pine-mic-live'), false, 'and cleared when the words land');

console.log('field dictation: tap, hold, append, focus passed');
'''),


]


TEST_2 = [  # tests/test_inline_field_dictation_2026_09_25.cjs


    (r'''const vm = require('node:vm');

function field(left, top) {
  const node = {
    tagName: 'INPUT', type: 'text', value: '', isConnected: true,
    disabled: false, readOnly: false, isContentEditable: false,
    parentElement: null, events: [], padding: '',
    style: {setProperty(name, value) { if (name === 'padding-right') node.padding = value; }},
    closest: () => null,
    hasAttribute: () => false,
    contains: () => false,
    getBoundingClientRect: () => ({left, top, right: left + 210,
''',
     r'''const vm = require('node:vm');

/* [field-mic-paint] Each field paints its own mic (talk-dot.js); there is
 * no layer and no button. A press is a real pointer event at the window, in
 * the capture phase, on the square the field paints at the right of its
 * padding box. */
function field(left, top) {
  const attrs = {};
  const node = {
    tagName: 'INPUT', type: 'text', value: '', isConnected: true, nodeType: 1,
    disabled: false, readOnly: false, isContentEditable: false,
    parentElement: null, events: [], padding: '', micSize: '',
    /* 210 x 38 with a 1px border */
    offsetWidth: 210, offsetHeight: 38, clientLeft: 1, clientTop: 1,
    clientWidth: 208, clientHeight: 36,
    style: {
      setProperty(name, value) {
        if (name === 'padding-right') node.padding = value;
        if (name === '--pine-mic-size') node.micSize = value;
      },
      removeProperty() {}, getPropertyValue: () => '', getPropertyPriority: () => '',
    },
    closest: selector => selector === '[data-pine-mic="on"]' && attrs['data-pine-mic'] === 'on' ? node : null,
    hasAttribute: name => name in attrs,
    getAttribute: name => name in attrs ? attrs[name] : null,
    setAttribute(name, value) { attrs[name] = String(value); },
    removeAttribute(name) { delete attrs[name]; },
    addEventListener() {}, setPointerCapture() {},
    contains: () => false,
    getBoundingClientRect: () => ({left, top, right: left + 210,
'''),


    (r'''  const fields = [field(20, 30), field(20, 90)];
  const dot = {id: 'pineTalkDot', setAttribute() {}};
  let layer;
  let clock = 1000;
  function element() {
''',
     r'''  const fields = [field(20, 30), field(20, 90)];
  const dot = {id: 'pineTalkDot', setAttribute() {}};
  const listeners = {};
  let clock = 1000;
  function element() {
'''),


    (r'''    };
  }
  const document = {
    body: {appendChild(node) { if (node.className === 'pine-field-mics') layer = node; }},
    createElement: element,
    getElementById: id => id === 'pineTalkDot' ? dot : null,
''',
     r'''    };
  }
  let appended = 0;
  const document = {
    body: {appendChild() { appended += 1; }},
    createElement: element,
    getElementById: id => id === 'pineTalkDot' ? dot : null,
'''),


    (r'''  const root = {
    document, navigator: {mediaDevices: {}}, innerWidth: 1000, innerHeight: 700,
    addEventListener() {}, getComputedStyle: () => ({paddingRight: '8px'}),
    setInterval: () => 1, clearInterval() {},
  };
''',
     r'''  const root = {
    document, navigator: {mediaDevices: {}}, innerWidth: 1000, innerHeight: 700,
    addEventListener(name, fn) { listeners[name] = fn; }, getComputedStyle: () => ({paddingRight: '8px'}),
    setInterval: () => 1, clearInterval() {},
  };
'''),


    (r'''    Event: class { constructor(type) { this.type = type; } },
  }, {filename: file});
  const buttons = layer.children;
  const takes = [];
  let finishes = 0;
  root.PineTalkDot.captureNext = callback => { takes.push(callback); return Promise.resolve(); };
  root.PineTalkDot.state = () => 'listening';
  root.PineTalkDot.finish = () => { finishes += 1; };
  const press = button => button.listeners.pointerdown({preventDefault() {}, pointerId: 1});
  return {fields, buttons, takes, press, now: value => { clock = value; },
    finishes: () => finishes};
}

''',
     r'''    Event: class { constructor(type) { this.type = type; } },
  }, {filename: file});
  const takes = [];
  let finishes = 0;
  let swallowed = 0;
  root.PineTalkDot.captureNext = callback => { takes.push(callback); return Promise.resolve(); };
  root.PineTalkDot.state = () => 'listening';
  root.PineTalkDot.finish = () => { finishes += 1; };
  /* the middle of the painted square: 2px in from the padding box's right
     edge, 32px, centred - (left + 1 + 208 - 2 - 16, top + 1 + 18) */
  const pointer = (node, x, y) => ({pointerId: 1, button: 0, pointerType: 'touch', clientX: x, clientY: y,
    target: node, preventDefault() { swallowed += 1; }, stopImmediatePropagation() {}});
  const at = (node, x, y) => listeners.pointerdown(pointer(node, x, y));
  const press = node => at(node, node.getBoundingClientRect().left + 191, node.getBoundingClientRect().top + 19);
  const release = node => listeners.pointerup(pointer(node, 0, 0));
  return {fields, takes, press, release, at, now: value => { clock = value; },
    finishes: () => finishes, swallowed: () => swallowed, appended: () => appended};
}

'''),


    (r'''    assert.match(source, /dotKeepVisible/, 'rotation and expanded capture keep the moved dot on screen');
    const h = load(file);
    assert.equal(h.buttons.length, 2, 'each editable input gets a mic');
    assert.equal(h.fields[0].padding, '44px', 'text makes room for its icon');
    assert.equal(h.buttons[0].style.left, '195px', 'mic sits inside right edge');
    assert.equal(h.buttons[1].style.top, '93px');
    h.press(h.buttons[0]);
    h.now(1100);
    h.buttons[0].listeners.pointerup();
    assert.equal(h.finishes(), 0, 'a tap keeps recording');
    h.press(h.buttons[0]);
    assert.equal(h.finishes(), 1, 'second tap stops');
    h.takes[0]('the station is listening');
''',
     r'''    assert.match(source, /dotKeepVisible/, 'rotation and expanded capture keep the moved dot on screen');
    const h = load(file);
    assert.deepEqual(h.fields.map(f => f.getAttribute('data-pine-mic')), ['on', 'on'],
      'each editable input gets a mic');
    assert.equal(h.appended(), 0, 'no layer, no button: the field is the mic');
    assert.equal(h.fields[0].padding, '44px', 'text makes room for its icon');
    assert.equal(h.fields[0].micSize, '32px', 'the plate is full size in a 38px field');
    h.at(h.fields[0], 60, 49);
    assert.equal(h.takes.length, 0, 'a press in the text belongs to the field');
    assert.equal(h.swallowed(), 0);
    h.at(h.fields[0], 188, 49);
    assert.equal(h.takes.length, 0, 'a press just left of the painted square is text');
    h.press(h.fields[0]);
    assert.equal(h.takes.length, 1, 'mic sits inside right edge');
    h.now(1100);
    h.release(h.fields[0]);
    assert.equal(h.finishes(), 0, 'a tap keeps recording');
    h.press(h.fields[0]);
    assert.equal(h.finishes(), 1, 'second tap stops');
    h.takes[0]('the station is listening');
'''),


    (r'''    assert.deepEqual(h.fields[0].events, ['input']);
    h.now(2000);
    h.press(h.buttons[1]);
    h.now(2500);
    h.buttons[1].listeners.pointerup();
    assert.equal(h.finishes(), 2, 'hold and release stops');
  }
''',
     r'''    assert.deepEqual(h.fields[0].events, ['input']);
    h.now(2000);
    h.press(h.fields[1]);
    h.now(2500);
    h.release(h.fields[1]);
    assert.equal(h.finishes(), 2, 'hold and release stops');
  }
'''),


]


TEST_3 = [  # tests/test_pine_segments_2026_09_21.cjs


    (r'''  assert.match(src, /history: true/);
  assert.doesNotMatch(src, /pseg-mic|pseg-topic-dictation/);
  assert.match(talkDot, /button\.className = 'pine-field-mic'/);
  assert.match(talkDot, /querySelectorAll\('input, textarea, \[contenteditable="true"\]'\)/);
  assert.match(src, /'\/api\/dj\/topics\/' \+ encodeURIComponent\(saved\.id\)/);
''',
     r'''  assert.match(src, /history: true/);
  assert.doesNotMatch(src, /pseg-mic|pseg-topic-dictation/);
  /* [field-mic-paint] the shared decorator marks every text field, and the
     field paints its own mic - no per-view button */
  assert.match(talkDot, /setAttribute\('data-pine-mic', value\)/);
  assert.match(talkDot, /querySelectorAll\('input, textarea, \[contenteditable="true"\]'\)/);
  assert.match(src, /'\/api\/dj\/topics\/' \+ encodeURIComponent\(saved\.id\)/);
'''),


]


FILES = [
    ("desktop/renderer/talk-dot.js", [(JS_OLD, JS_NEW)]),
    ("app/src/main/assets/pine-views/talk-dot.js", [(JS_OLD, JS_NEW)]),
    ("desktop/renderer/view-chrome.css", [(CSS_OLD, CSS_NEW)]),
    ("app/src/main/assets/pine-views/view-chrome.css", [(CSS_OLD, CSS_NEW)]),
    ("tests/test-field-dictation.cjs", TEST_1),
    ("tests/test_inline_field_dictation_2026_09_25.cjs", TEST_2),
    ("tests/test_pine_segments_2026_09_21.cjs", TEST_3),
]


def _eol(text):
    return "\r\n" if "\r\n" in text else "\n"


def _status(text, pairs):
    """ready: no marker and every old hunk exactly once; applied: marker and
    every new hunk exactly once with no old hunk left outside them."""
    eol = _eol(text)
    subs = [(old.replace("\n", eol), new.replace("\n", eol)) for old, new in pairs]
    if MARK in text:
        rest = text
        for _old, new in subs:
            if rest.count(new) != 1:
                return "missing", subs
            rest = rest.replace(new, "\0")
        if any(rest.count(old) for old, _new in subs):
            return "missing", subs
        return "applied", subs
    if all(text.count(old) == 1 for old, _new in subs):
        return "ready", subs
    return "missing", subs


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".field-mic-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv):
    do_apply = "--apply" in argv
    root = next((a for a in argv if not a.startswith("--")), ".")
    states = []
    for rel, pairs in FILES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print("missing  %s (no such file)" % rel)
            states.append(("missing", rel, path, None, None))
            continue
        text = _read(path)
        state, subs = _status(text, pairs)
        print("%-8s %s (%s, %d hunk%s)" % (state, rel, "CRLF" if _eol(text) == "\r\n" else "LF",
                                          len(subs), "" if len(subs) == 1 else "s"))
        states.append((state, rel, path, text, subs))
    if any(s[0] == "missing" for s in states):
        return 1
    if not do_apply:
        return 2 if all(s[0] == "applied" for s in states) else 0
    for state, rel, path, text, subs in states:
        if state != "ready":
            continue
        patched = text
        for old, new in subs:
            assert patched.count(old) == 1, (rel, old[:60])
            patched = patched.replace(old, new, 1)
        assert MARK in patched and _status(patched, [(o.replace("\r\n", "\n"), n.replace("\r\n", "\n"))
                                                     for o, n in subs])[0] == "applied", rel
        # line endings kept: a CRLF file gains no bare LF, an LF file no CRLF
        bare = lambda t: t.count("\n") - t.count("\r\n")
        if _eol(text) == "\r\n":
            assert bare(patched) == bare(text), rel
        else:
            assert patched.count("\r\n") == text.count("\r\n"), rel
        _write(path, patched)
        print("applied  %s" % rel)
    for rel, _pairs in FILES:
        with open(os.path.join(root, rel), "rb") as fh:
            print("md5 %s  %s" % (hashlib.md5(fh.read()).hexdigest(), rel))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
