/* Operator review of real cuts. Reading and voting never start playback. */
const BASE = '/api/orchestrator/rejections';
const POLICY = '/api/orchestrator/rejection-policy';
const LEARNING = '/api/orchestrator/prompt-learning';
const asText = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
const label = value => String(value || 'Unknown').replace(/_/g, ' ');
const time = value => {
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString();
};

// Advance only through the events actually delivered, including a burst that
// needs several pages. latest_cursor is the server head, not an acknowledgement.
export function eventCursor(data, previous = 0) {
  if (!previous && !(data.events || []).length && !data.events_has_more) return Number(data.latest_cursor) || 0;
  if (data.next_after != null && Number.isFinite(Number(data.next_after))) return Math.max(previous, Number(data.next_after));
  const events = data.events || [];
  if (events.length) return Math.max(previous, ...events.map(row => Number(row.seq) || 0));
  return data.events_has_more ? previous : Math.max(previous, Number(data.latest_cursor) || 0);
}

export function reviewOccurrence(row) {
  const value = Number(row?.event_seq ?? row?.review_seq ?? row?.seq);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

export function reviewDetailPath(id, eventSeq) {
  return BASE + '/' + encodeURIComponent(id) + (reviewOccurrence({event_seq:eventSeq}) ? '?event_seq=' + Number(eventSeq) : '');
}

export function workbenchPending(operation) {
  return !!operation && operation.lease_expired !== true && ['pending', 'queued', 'running', 'applying'].includes(operation.status);
}

export function workbenchItems(value) {
  return Array.isArray(value) ? value : Array.isArray(value?.items) ? value.items : [];
}

export function create(options = {}) {
  if (window.PineRejectionReview && !window.PineRejectionReview.destroyed) {
    window.PineRejectionReview.configure(options);
    return window.PineRejectionReview;
  }
  let request = options.request || window.api;
  if (typeof request !== 'function') throw new Error('The rejection review needs the station API.');
  let hooks = {...options};
  const desktop = /Electron\//i.test(navigator.userAgent) || window.__pineRejectionNotificationOwner === 'desktop';
  const notifications = options.notifications == null ? !desktop : !!options.notifications;
  /* SWITCHED OFF FOR THIS SCREEN, AND REMEMBERED.
   *
   * localStorage is already per screen - that is the whole reason it is the
   * right store here rather than a station setting. A tablet on a wall
   * showing the script all day gives these up; the desktop beside it keeps
   * them. The key is deliberately plain and shared in shape, so any other
   * notice this panel raises can honour the same decision. */
  const quietKey = 'pine-notices-off:' + location.origin;
  let silenced = false;
  try { silenced = localStorage.getItem(quietKey) === '1'; } catch (_) { /* private browser */ }
  function silence(off) {
    silenced = !!off;
    try { localStorage.setItem(quietKey, silenced ? '1' : '0'); }
    catch (_) { /* a preference is not worth an exception */ }
    if (silenced) dismissNotice();
  }
  let disposed = false, timer = null, polling = null, cursor = 0, booted = false;
  let dialog = null, panel = null, queue = null, detail = null, count = null, notice = null;
  let selected = null, selectedEvent = null, selection = 0, listVersion = 0, queueReads = 0, rows = new Map(), nextBefore = null;
  let status = 'pending', gate = '', policy = null, policyDirty = false, policyBusy = false;
  let mutation = '', batchRequestId = '', labMutationKey = '';
  let batchFeedback = {text: '', error: false};
  const learning = {data:null, draft:null, dirty:false, open:false, loading:false,
    read:0, feedback:'', error:false};
  let total = 0, unreviewed = 0, newCount = 0, newestId = null, newestEvent = null, returnFocus = null, bootstrapHead = 0;
  const reads = new Set();
  const workbenches = new Map();
  const cursorKey = 'pine-rejection-cursor:' + location.origin;
  const batchKey = 'pine-rejection-batch:' + location.origin;
  try { cursor = Number(sessionStorage.getItem(cursorKey)) || 0; } catch (_) { /* private browser */ }
  try { batchRequestId = sessionStorage.getItem(batchKey) || ''; } catch (_) { /* private browser */ }
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function button(text, action, cls) {
    const node = el('button', text, cls); node.type = 'button'; node.onclick = action; return node;
  }
  async function get(path) {
    const controller = new AbortController(); reads.add(controller);
    const timeout = setTimeout(() => controller.abort(), 15000);
    try { return await request(path, {signal: controller.signal}); }
    finally { clearTimeout(timeout); reads.delete(controller); }
  }
  function say(target, text, error = false) {
    if (!target) return;
    target.textContent = text; target.classList.toggle('prr-error', error);
  }
  function badge() {
    document.dispatchEvent(new CustomEvent('pine-rejection-count', {detail: {unreviewed, total}}));
    if (count) count.textContent = unreviewed + ' awaiting review';
    paintMutations();
  }
  function paintMutations() {
    if (!panel) return;
    panel.querySelectorAll('[data-policy], .prr-gate-policy input, [data-decision], [data-lab-mutation], [data-learning], [data-learning-rollback]').forEach(node => {
      node.disabled = !!mutation || (!!node.dataset.policy && !policy)
        || node.dataset.technical === 'true' || node.dataset.stale === 'true' || node.dataset.unavailable === 'true';
    });
    const approve = panel.querySelector('[data-review="approve-current"]');
    if (approve) {
      approve.disabled = !!mutation || (!unreviewed && !batchRequestId);
      approve.textContent = mutation === 'batch' ? 'Approving…'
        : batchRequestId ? 'Retry approval' : 'Approve all';
    }
  }
  function rememberBatch(id) {
    batchRequestId = id;
    try { if (id) sessionStorage.setItem(batchKey, id); else sessionStorage.removeItem(batchKey); }
    catch (_) { /* retain the same ID in memory when browser storage is unavailable */ }
  }
  function sayBatch(text, error = false) {
    batchFeedback = {text, error};
    say(panel?.querySelector('.prr-batch-result'), text, error);
  }
  function newBatchId() {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
  }
  async function approveCurrent() {
    if (mutation || (!unreviewed && !batchRequestId)) return;
    mutation = 'batch';
    try {
      if (!batchRequestId) rememberBatch(newBatchId());
      paintMutations();
      sayBatch('Approving the current pending batch across every page and gate…');
      const result = await request(BASE + '/approve-current', {method: 'POST', body: JSON.stringify({request_id: batchRequestId})});
      if (result.ok === false) throw new Error(result.error || result.detail || 'The batch was not confirmed.');
      rememberBatch('');
      const approved = Number(result.approved) || 0, skipped = Number(result.skipped) || 0;
      const reasonEntries = Array.isArray(result.skip_reasons)
        ? result.skip_reasons.map(item => typeof item === 'string' ? item : [item.reason || item.status, item.count].filter(value => value != null).join(': '))
        : Object.entries(result.skip_reasons || {}).map(([reason, amount]) => label(reason) + ': ' + amount);
      const parts = ['Approved ' + approved + ' current line' + (approved === 1 ? '.' : 's.')];
      if (result.queued != null) parts.push((Number(result.queued) || 0) + ' queued for recording.');
      if (result.awaiting_recovery != null) parts.push((Number(result.awaiting_recovery) || 0) + ' awaiting recovery.');
      if (result.needs_context) parts.push(Number(result.needs_context) + ' need more context.');
      parts.push('Skipped ' + skipped + (reasonEntries.length ? ' (' + reasonEntries.join('; ') + ').' : '.'));
      if (result.remaining_pending != null) {
        unreviewed = Number(result.remaining_pending) || 0;
        parts.push(unreviewed + ' still awaiting review.');
      }
      parts.push('This batch only; future rejections are unchanged. No playback was requested.');
      sayBatch(parts.join(' '));
      // A retry returns the original batch snapshot. A newer policy already
      // read from the station must not be replaced by that historical value.
      if (result.policy && (!policy || Number(result.policy.revision || 0) >= Number(policy.revision || 0))) policy = result.policy;
      badge();
      if (dialog) await loadQueue(true);
      // Refresh the current selection, including a panel reopened during the
      // approval. A subsequent navigation still invalidates this read.
      const reviewing = dialog && selected ? {id: selected, eventSeq:selectedEvent, token: selection, dialog} : null;
      if (reviewing && dialog === reviewing.dialog && selected === reviewing.id && selection === reviewing.token) {
        try {
          const row = await get(reviewDetailPath(reviewing.id, reviewing.eventSeq));
          if (dialog === reviewing.dialog && selected === reviewing.id && selection === reviewing.token && !disposed) {
            // Read the note after the request: edits made while it was pending
            // belong to the operator, including an intentionally empty note.
            const note = detail.querySelector('.prr-verdict textarea');
            const active = document.activeElement === note;
            const caret = note ? [note.selectionStart, note.selectionEnd] : null;
            paintDetail(row, note?.value);
            if (active) {
              const replacement = detail.querySelector('.prr-verdict textarea');
              replacement.focus();
              if (caret) replacement.setSelectionRange(...caret);
            }
          }
        } catch (error) {
          if (dialog === reviewing.dialog && selected === reviewing.id && selection === reviewing.token) {
            detail.querySelectorAll('[data-decision]').forEach(node => { node.dataset.stale = 'true'; });
            say(detail.querySelector('.prr-review-result'), 'Approval saved. Refresh this record before making another decision: ' + error.message, true);
          }
        }
      }
    } catch (error) {
      sayBatch('Approval not confirmed: ' + error.message + '. Retry checks the same request to avoid approving a second batch.', true);
    } finally {
      mutation = ''; paintMutations(); paintPolicy();
    }
  }
  function dismissNotice() { if (notice) notice.remove(); notice = null; newCount = 0; }

  /* LATER MEANS THE ORCHESTRATOR TAKES IT.
   *
   * It used to mean only "go away", so the same queue interrupted the same
   * person again a few minutes later, forever - which is not what anybody
   * pressing Later intends. `regrade` re-reads every pending cut against
   * today's grader and makes the calls itself; the road has existed since
   * 2026-09-08 and nothing was pointed at it.
   *
   * The card is dismissed FIRST and the ask sent after. The operator has
   * said they are done with it either way, and a card that hangs about
   * saying "asking…" for as long as a grader pass takes is the interruption
   * they were trying to end. */
  async function handOver() {
    dismissNotice();
    try {
      await request(BASE + '/regrade', {method: 'POST'});
    } catch (error) {
      /* Said once, quietly, and only because a silent failure here means the
       * queue is untouched while the operator believes it is being worked. */
      try { console.warn('[rejections] the orchestrator was not reached: ' + error.message); }
      catch (_) { /* no console */ }
    }
  }

  function showNotice() {
    if (!notifications || silenced || disposed || dialog || !newCount) return;
    if (!notice) {
      notice = el('aside', null, 'prr-notice'); notice.dataset.rejectionReview = 'notice';
      notice.setAttribute('aria-label', 'Rejected lines');
      /* THE CORNER SWITCH. In the corner because that is where a thing you
       * want gone is looked for, and it silences this screen for good rather
       * than closing one card - the difference is said in the tooltip,
       * because the two are a tap apart. */
      const off = button('\u00d7', () => silence(true), 'prr-notice-off');
      off.title = 'Stop showing these notices on this screen. '
        + 'The queue stays reachable from the Rejected lines badge.';
      off.setAttribute('aria-label', 'Stop notices on this screen');
      const title = el('strong', '', 'prr-notice-title'); title.setAttribute('role', 'status');
      const text = el('p', 'Includes unsuccessful rewrites and retries. Inspect the words, the failed checks and the orchestrator’s repair workflow.');
      const actions = el('div', null, 'prr-actions');
      const later = button('Later', handOver);
      later.title = 'Hand it to the orchestrator: it re-reads every pending cut '
        + 'against today’s grader and makes the calls itself.';
      actions.append(button('Review lines', () => open(newestId, newestEvent)), later);
      /* APPENDED LAST ON PURPOSE. The stylesheet paints
       * `.prr-notice button:first-child` green as the primary action, so a
       * switch put in first would steal that and look like the thing to
       * press. It is absolutely positioned, so DOM order costs nothing. */
      notice.append(title, text, actions, off); document.body.append(notice);
    }
    notice.querySelector('strong').textContent = newCount === 1 ? 'A rejection needs review' : newCount + ' rejection updates';
  }
  async function poll() {
    if (disposed || polling) return polling;
    polling = (async () => {
      let more = false;
      try {
        for (let page = 0; page < 3; page++) {
          const oldCursor = cursor;
          const data = await get(BASE + '?limit=50&status=pending&after=' + encodeURIComponent(cursor));
          if (disposed) return;
          const events = (data.events || []).filter(row => Number(row.seq) > oldCursor);
          cursor = eventCursor(data, cursor);
          try { sessionStorage.setItem(cursorKey, String(cursor)); } catch (_) { /* private browser */ }
          unreviewed = Number(data.unreviewed) || 0; total = Number(data.total) || 0;
          if (data.policy && !policyDirty && !policyBusy) { policy = data.policy; paintPolicy(); }
          if (!booted && !oldCursor) {
            newCount = unreviewed; bootstrapHead = Number(data.latest_cursor) || 0;
            newestId = data.items?.[0]?.id || events.at(-1)?.id || null;
            newestEvent = reviewOccurrence(data.items?.[0] || events.at(-1));
          } else if (events.length) {
            const unseen = events.filter(row => Number(row.seq) > bootstrapHead);
            newCount += unseen.length;
            if (unseen.length) { newestId = unseen.at(-1).id; newestEvent = reviewOccurrence(unseen.at(-1)); }
          }
          booted = true; badge(); showNotice();
          more = !!data.events_has_more && cursor > oldCursor;
          if (!more) break;
        }
        if (dialog && !queueReads) await loadQueue(false);
      } catch (error) {
        if (dialog && error.name !== 'AbortError') say(panel.querySelector('.prr-connection'), 'Review updates unavailable: ' + error.message, true);
      } finally {
        polling = null;
        clearTimeout(timer);
        if (!disposed) timer = setTimeout(poll, more ? 250 : 4000);
      }
    })();
    return polling;
  }
  function section(parent, title, value, open = false) {
    const wrap = el('details', null, 'prr-section'); wrap.open = open;
    wrap.append(el('summary', title), el('pre', asText(value) || 'Not supplied by this gate.'));
    parent.append(wrap); return wrap;
  }
  function paintQueue() {
    if (!queue) return;
    const focused = queue.contains(document.activeElement) ? document.activeElement.dataset.reviewId : null;
    queue.replaceChildren();
    const items = [...rows.values()].sort((a, b) => Number(b.seq) - Number(a.seq));
    for (const row of items) {
      const item = button('', () => select(row.id, reviewOccurrence(row)), 'prr-row');
      item.dataset.reviewId = row.id; item.setAttribute('aria-pressed', String(row.id === selected));
      item.append(el('span', (row.who ? row.who + ' · ' : '') + label(row.gate), 'prr-row-meta'),
        el('span', row.preview || row.candidate_preview || row.source_preview || row.reason || (row.reasons || []).map(asText).join(' · ') || 'Inspect this rejection', 'prr-row-preview'),
        el('small', [time(row.at), label(row.review_status || 'pending'), row.technical ? 'Technical' : '', Number(row.occurrences) > 1 ? row.occurrences + ' occurrences' : ''].filter(Boolean).join(' · ')));
      queue.append(item);
    }
    if (!items.length) queue.append(el('p', 'No matching rejected lines.', 'prr-empty'));
    const more = panel.querySelector('.prr-more'); more.hidden = !nextBefore;
    if (focused) [...queue.children].find(node => node.dataset.reviewId === focused)?.focus();
  }
  async function loadQueue(reset = true, older = false) {
    if (!dialog) return;
    const version = ++listVersion;
    const params = new URLSearchParams({limit: '50', status});
    if (gate) params.set('gate', gate);
    if (older && nextBefore) params.set('before', nextBefore);
    queueReads++;
    try {
      const data = await get(BASE + '?' + params);
      if (!dialog || disposed || version !== listVersion) return;
      if (reset) rows = new Map();
      else if (!older && status === 'pending') {
        const latest = data.items || [], ids = new Set(latest.map(row => row.id));
        const floor = latest.length ? Math.min(...latest.map(row => Number(row.seq) || 0)) : 0;
        for (const [id, row] of rows) if (Number(row.seq) >= floor && !ids.has(id)) rows.delete(id);
      }
      for (const row of data.items || []) rows.set(row.id, row);
      if (reset || older) nextBefore = data.has_more ? data.next_before : null;
      total = Number(data.total) || 0; unreviewed = Number(data.unreviewed) || 0;
      if (data.policy && !policyDirty && !policyBusy) policy = data.policy;
      badge(); paintQueue(); paintPolicy(); paintGates();
      say(panel.querySelector('.prr-connection'), 'Reviewing does not play or replay audio.');
    } catch (error) {
      if (dialog && version === listVersion && error.name !== 'AbortError') say(panel.querySelector('.prr-connection'), error.message, true);
    } finally { queueReads--; }
  }
  function paintGates() {
    if (!panel) return;
    const select = panel.querySelector('[data-filter="gate"]');
    const known = new Set([...select.options].map(option => option.value).filter(Boolean));
    for (const row of rows.values()) if (row.gate) known.add(row.gate);
    for (const name of policy?.disabled_gates || []) known.add(name);
    for (const name of [...known].sort()) if (![...select.options].some(option => option.value === name)) {
      const option = el('option', label(name)); option.value = name; select.append(option);
    }
    select.value = gate;
    if (!policyDirty && !policyBusy) paintGatePolicy([...known]);
  }
  function paintGatePolicy(known) {
    const area = panel.querySelector('.prr-gate-policy'); area.replaceChildren();
    for (const name of known) {
      const row = el('label'); const input = el('input'); input.type = 'checkbox';
      input.dataset.gate = name; input.checked = !(policy?.disabled_gates || []).includes(name);
      input.onchange = () => { policyDirty = true; };
      row.append(input, document.createTextNode(' Reject editorial flags at ' + label(name))); area.append(row);
    }
    if (!known.length) area.append(el('p', 'Individual gates appear after their first recorded cut.'));
    paintMutations();
  }
  function paintPolicy() {
    if (!panel || !policy) return;
    const master = panel.querySelector('[data-policy="master"]');
    master.setAttribute('aria-checked', String(policy.enabled !== false));
    master.querySelector('.prr-switch-value').textContent = policy.enabled === false ? 'Off' : 'On';
    panel.querySelector('.prr-policy-state').textContent = policy.enabled === false ? 'Editorial rejection is stopped. Technical checks still apply.' : 'Editorial rejection is enabled. Higher allowance accepts more lines.';
    paintMutations();
    if (policyDirty || policyBusy) return;
    panel.querySelector('[data-policy="max_faults"]').value = String(policy.max_faults ?? 0);
    panel.querySelector('.prr-policy-caption').textContent = 'Allow up to ' + (policy.max_faults ?? 0) + ' editorial flags';
  }
  async function savePolicy(toggle = false) {
    if (!policy || mutation) return;
    const value = Number(panel.querySelector('[data-policy="max_faults"]').value);
    const feedback = panel.querySelector(toggle ? '.prr-master-result' : '.prr-policy-result');
    const dirtyBefore = policyDirty;
    if (!toggle && (!Number.isInteger(value) || value < 0 || value > 10)) { say(feedback, 'Choose a whole number from 0 to 10.', true); return; }
    const change = toggle ? {enabled: policy.enabled === false} : {
      max_faults: value,
      disabled_gates: [...panel.querySelectorAll('.prr-gate-policy input')].filter(input => !input.checked).map(input => input.dataset.gate),
    };
    if (policy.revision != null) change.expected_revision = policy.revision;
    policyBusy = true; mutation = 'policy'; paintMutations();
    try {
      const result = await request(POLICY, {method: 'POST', body: JSON.stringify(change)});
      if (result.ok === false) throw new Error(result.error || result.detail || 'Policy was not saved.');
      policy = result.policy || result; policyDirty = toggle ? dirtyBefore : false;
      say(feedback, toggle ? (policy.enabled === false ? 'Rejection system off. Technical checks remain enabled.' : 'Rejection system on.')
        + (dirtyBefore ? ' Your unsaved allowance and gate edits are retained.' : '')
        : 'Saved for future decisions. Existing cuts remain available for review.');
    } catch (error) {
      say(feedback, 'Policy not saved: ' + error.message, true);
      if (toggle) {
        // A concurrent operator may have advanced the policy revision. Refresh
        // the switch's real state without overwriting unsaved advanced fields.
        try {
          const data = await get(POLICY); const current = data.policy || data;
          if (current && (!policy || Number(current.revision || 0) >= Number(policy.revision || 0))) policy = current;
        } catch (_) { /* preserve the original failure beside the master switch */ }
      }
    }
    finally {
      policyBusy = false; mutation = '';
      if (panel) { paintMutations(); paintPolicy(); paintGates(); }
    }
  }
  function acceptLearning(data) {
    const current = data?.status;
    if (!current || !Number.isSafeInteger(Number(current.revision))) throw new Error('The station did not return a learning revision.');
    if (learning.data && Number(current.revision) < Number(learning.data.status.revision)) return;
    learning.data = data;
    if (!learning.dirty) learning.draft = {enabled:current.enabled === true, mode:current.mode === 'fluid' ? 'fluid' : 'strict'};
  }
  async function loadLearning(preserveFeedback = false) {
    if (learning.loading || disposed) return;
    const token = ++learning.read;
    learning.loading = true; paintLearning();
    try {
      const data = await get(LEARNING);
      if (disposed || token !== learning.read) return;
      if (data.ok === false) throw new Error(data.detail || data.error || 'Learning status unavailable.');
      acceptLearning(data);
      if (!preserveFeedback) { learning.feedback = learning.dirty ? 'Saved status refreshed. Your unsaved learning settings are retained.' : ''; learning.error = false; }
    } catch (error) {
      if (token === learning.read && error.name !== 'AbortError' && !preserveFeedback) {
        learning.feedback = 'Learning status unavailable: ' + error.message; learning.error = true;
      }
    } finally {
      if (token === learning.read) { learning.loading = false; paintLearning(); }
    }
  }
  async function changeLearning(action, revision = null) {
    if (mutation || !learning.data?.status || learning.loading) return;
    const body = {expected_revision:Number(learning.data.status.revision)};
    let path = LEARNING;
    if (action === 'save') Object.assign(body, learning.draft);
    else if (action === 'resume') body.resume = true;
    else if (action === 'rollback') { path += '/rollback'; body.revision = revision; }
    else if (action === 'refresh') path += '/refresh';
    else return;
    mutation = 'learning';
    learning.feedback = action === 'refresh' ? 'Reviewing retained declines for distinct patterns…' : 'Saving prompt learning changes…';
    learning.error = false; paintLearning(); paintMutations();
    try {
      const result = await request(path, {method:'POST', body:JSON.stringify(body)});
      if (result.ok === false) throw new Error(result.detail || result.error || 'The learning change was not confirmed.');
      acceptLearning(result);
      if (action === 'save') {
        learning.dirty = false;
        learning.draft = {enabled:learning.data.status.enabled === true,mode:learning.data.status.mode};
      }
      const saved = result.status;
      learning.feedback = 'Saved revision ' + saved.revision + '. ' + (action === 'refresh'
        ? 'Reviewed ' + (Number(result.observed) || 0) + ' retained declines. Active hints follow distinct-source evidence.'
        : action === 'rollback' ? 'Restored revision ' + revision + '. Automatic changes are paused until you resume them.'
        : action === 'resume' ? (saved.enabled ? 'Automatic changes resumed.' : 'Rollback pause cleared. Automatic learning remains off.') : 'Learning is ' + (saved.enabled ? 'on' : 'off') + '; acceptance mode is ' + label(saved.mode) + '.');
      if (learning.dirty) learning.feedback += ' Your unsaved learning settings are retained.';
      learning.feedback += ' Existing lines and audio were not replayed.';
    } catch (error) {
      learning.feedback = 'Change not confirmed: ' + error.message + '. Saved status will be reloaded; your draft is retained.';
      learning.error = true;
      await loadLearning(true);
    } finally { mutation = ''; paintLearning(); paintMutations(); }
  }
  function paintLearning() {
    const target = panel?.querySelector('.prr-learning-body'); if (!target) return;
    const focused = target.contains(document.activeElement) ? document.activeElement.dataset.learning : null;
    target.replaceChildren();
    const saved = learning.data?.status;
    const summary = panel.querySelector('.prr-learning-caption');
    if (summary) summary.textContent = saved ? ' · ' + label(saved.mode) + ' · revision ' + saved.revision : '';
    target.append(el('p','The orchestrator tracks fresh rewrite successes and failures, learns from individual reviews, and tries bounded prompt recipes when a recurring fault persists. Your saved crystal instruction stays part of the prompt.','prr-muted'));
    const controls = el('div',null,'prr-learning-controls');
    const enabledLabel = el('label',null,'prr-learning-enabled');
    const enabled = el('input'); enabled.type = 'checkbox'; enabled.setAttribute('role','switch');
    enabled.dataset.learning = 'enabled'; enabled.checked = learning.draft?.enabled === true;
    enabled.setAttribute('aria-label','Automatically learn prompt reminders'); enabled.setAttribute('aria-checked',String(enabled.checked));
    enabled.dataset.unavailable = String(!saved || learning.loading);
    enabled.onchange = () => {learning.draft.enabled=enabled.checked;learning.dirty=true;enabled.setAttribute('aria-checked',String(enabled.checked));};
    enabledLabel.append(enabled,document.createTextNode(' Automatically learn prompt reminders'));
    const modeLabel = el('label','Acceptance mode'); const mode = el('select'); mode.dataset.learning = 'mode'; mode.setAttribute('aria-label','Crystal acceptance mode');
    for (const [value,text] of [['strict','Strict · all rewrite checks'],['fluid','Fluid · flexible style, rhyme required']]) {
      const option=el('option',text);option.value=value;mode.append(option);
    }
    mode.value=learning.draft?.mode || 'strict';mode.dataset.unavailable=String(!saved || learning.loading);
    mode.onchange=()=>{learning.draft.mode=mode.value;learning.dirty=true;};modeLabel.append(mode);
    controls.append(enabledLabel,modeLabel);target.append(controls);
    target.append(el('p','Fluid treats transformation and crystal vocabulary as style advisories. Meaning, rhyme, speaker structure, copying and technical checks still apply. Turning learning off stops automatic hints; acceptance mode is a separate choice.','prr-learning-scope'));
    const actions=el('div',null,'prr-actions');
    const action=(text,key,fn,unavailable=!saved || learning.loading)=>{const node=button(text,fn);node.dataset.learning=key;node.dataset.unavailable=String(unavailable);actions.append(node);return node;};
    action('Save learning settings','save',()=>changeLearning('save')).classList.add('prr-primary');
    action('Learn from recent declines','refresh',()=>changeLearning('refresh'));
    action('Reload saved status','reload',()=>loadLearning(),learning.loading);
    if (saved?.automation_paused) action('Resume automatic changes','resume',()=>changeLearning('resume'));
    target.append(actions);
    const result=el('p',learning.feedback || (learning.loading ? 'Loading saved learning status…' : saved?.say || ''),'prr-learning-result');
    result.setAttribute('role','status');result.classList.toggle('prr-error',learning.error);target.append(result);
    if (learning.data?.errors?.length || Number(learning.data?.errors?.count) > 0) section(target,'Learning observation errors',learning.data.errors);
    if (saved) {
      const outcomes=saved.outcomes;
      const measured=el('div',null,'prr-learning-outcomes');measured.append(el('h4','Are the changes helping?'));
      measured.append(el('p',Number.isInteger(outcomes?.observations)
        ? outcomes.observations+' measured production attempts. First attempts and repairs are reported separately; repeated tries of one source do not become extra source lines in a comparison.'
        : 'Measured outcome history is not available yet. Retained rejection counts alone cannot show a pass rate.'));
      measured.append(el('p','An exploring recipe is still an experiment. A supported recipe has better observed results in a comparable group with no higher factual or rhyme failure rate. These checks do not prove that every line sounds good.','prr-muted'));
      measured.append(el('p','Only returned text with complete checks enters these quality figures. Admission waits and malformed replies remain in Trace.','prr-muted'));
      for (const [key,title] of [['first','First attempts'],['repair','Repairs']]) {
        const figures=outcomes?.measured_attempts?.[key];
        if(Number.isInteger(figures?.attempts)) measured.append(el('p',title+': '+figures.attempts+' checked; '
          +figures.effective_passes+' accepted under the saved acceptance rules; '+figures.raw_passes+' passed all raw checks.'));
      }
      if(outcomes) section(measured,'Measured attempts and comparable source groups',outcomes);
      target.append(measured);
      const hints=el('div',null,'prr-learning-hints');hints.append(el('h4','Active prompt reminders'));
      if (!saved.enabled) hints.append(el('p','Learning is off. Retained reminders are not included in future prompts.','prr-muted'));
      if (!(saved.hints || []).length) hints.append(el('p','This revision has no active reminders. Automatic hints need three distinct source lines across at least two known original scripts.','prr-muted'));
      for (const hint of saved.hints || []) {
        const card=el('article',null,'prr-learning-hint');card.append(el('strong',label(hint.kind || 'all roads')+' · '+label(hint.pattern)),el('p',hint.text));
        if(hint.phase) card.append(el('p','Recipe '+(hint.recipe_version || 1)+' · '+label(hint.phase)+'. '+(hint.recipe_reason || ''),'prr-learning-recipe'));
        card.append(el('small','Activated from '+hint.sources+' source lines across '+hint.parents+' scripts. '+(hint.operator_confirmed || 0)+' individually confirmed.'));
        const evidence=el('details');evidence.append(el('summary','Supporting cut occurrences'));
        const refs=el('div',null,'prr-actions');
        for (const ref of hint.evidence || []) {
          const link=button(String(ref.review_id).slice(0,12)+' · event '+ref.event_seq,async()=>{if(dialog){await select(ref.review_id,ref.event_seq);detail?.scrollIntoView({block:'start'});}});
          link.dataset.learningEvidence=ref.review_id;link.dataset.eventSeq=ref.event_seq;refs.append(link);
        }
        evidence.append(refs);if(hint.evidence_omitted) evidence.append(el('small',hint.evidence_omitted+' additional supporting source lines.'));
        card.append(evidence);hints.append(card);
      }
      target.append(hints);
      section(target,'Current support and excluded observations',{patterns:saved.patterns,excluded:saved.excluded,observation_count:saved.observation_count,observation_limit:saved.observation_limit,basis:saved.basis});
      if(saved.classification) section(target,'Failure classification corrections',{
        ...saved.classification,history:learning.data.classification_history});
      const history=el('details',null,'prr-learning-history');history.append(el('summary','Revision history and rollback'));
      history.append(el('p','Restoring a revision restores its reminders, mode and learning switch. Automatic changes then pause until you explicitly resume them.'));
      for (const entry of workbenchItems(learning.data.history)) {
        const item=el('article',null,'prr-learning-revision');
        item.append(el('strong','Revision '+entry.revision+' · '+label(entry.reason)),el('small',time(entry.at)));
        section(item,'Recorded change',{before:entry.before,after:entry.after,trigger:entry.trigger});
        if(Number(entry.revision)!==Number(saved.revision)) {
          const undo=button('Restore revision '+entry.revision,()=>changeLearning('rollback',Number(entry.revision)));
          undo.dataset.learningRollback=entry.revision;undo.dataset.unavailable=String(learning.loading);item.append(undo);
        }
        history.append(item);
      }
      target.append(history);
    }
    paintMutations();
    if(focused) target.querySelector('[data-learning="'+focused+'"]')?.focus();
  }
  async function select(id, eventSeq = null) {
    selected = String(id); selectedEvent = reviewOccurrence({event_seq:eventSeq}); const token = ++selection; paintQueue();
    detail.replaceChildren(el('p', 'Loading the complete record…', 'prr-empty'));
    try {
      const row = await get(reviewDetailPath(id, selectedEvent));
      if (!dialog || token !== selection || disposed) return;
      if (selectedEvent && reviewOccurrence(row) !== selectedEvent) throw new Error('The server did not return the requested occurrence. Refresh the current cut to continue.');
      selectedEvent = selectedEvent || reviewOccurrence(row);
      paintDetail(row);
    } catch (error) {
      if (dialog && token === selection && error.name !== 'AbortError') detail.replaceChildren(el('p', error.message, 'prr-error'), button('Retry', () => select(id, eventSeq)));
    }
  }
  function paintDetail(row, retainedNote = null) {
    detail.replaceChildren();
    detail.append(el('h3', (row.context?.who || row.who || 'Line') + ' · ' + label(row.gate)),
      el('p', time(row.at) + (row.id ? ' · ' + row.id : ''), 'prr-muted'));
    section(detail, 'Candidate considered by the gate — full text', row.candidate, true);
    const grades = el('div', null, 'prr-grades');
    const machine = el('div', null, 'prr-grade'); machine.append(el('h4', 'Machine decision and reasons'));
    const reasons = row.reasons || row.reason;
    machine.append(el('p', Array.isArray(reasons) ? reasons.map(asText).join('\n') : asText(reasons) || 'No reason supplied by this gate.'));
    section(machine, 'Full machine evaluation', {evaluation: row.evaluation, technical: row.technical || false});
    const operator = el('div', null, 'prr-grade'); operator.append(el('h4', 'Operator decision'));
    const statuses = {pending: 'Awaiting review', allowed: row.decision?.scope === 'instance' ? 'Approved once' : 'Should not reject', kept: 'Rejection is correct'};
    operator.append(el('p', statuses[row.review_status || 'pending'] || label(row.review_status)));
    if (row.effect?.say) operator.append(el('p', row.effect.say));
    if (row.decision?.note) operator.append(el('p', 'Review note: ' + row.decision.note));
    section(operator, 'Decision details', {status: row.review_status || 'pending', revision: row.revision, decision: row.decision || null, effect: row.effect || null});
    grades.append(machine, operator); detail.append(grades);
    const form = el('div', null, 'prr-verdict'); const noteLabel = el('label', 'Review note (optional)');
    const note = el('textarea'); note.rows = 2; note.value = retainedNote ?? row.decision?.note ?? ''; note.placeholder = 'What should the station learn from this decision?';
    noteLabel.append(note); form.append(noteLabel);
    const result = el('p', '', 'prr-review-result'); result.setAttribute('role', 'status');
    const actions = el('div', null, 'prr-actions');
    const allow = button('Should not reject', () => vote('allow'), 'prr-primary');
    const keep = button('Rejection is correct', () => vote('keep'));
    const technical = !!row.technical;
    const stale = row.read_only === true || row.occurrence_current === false;
    allow.dataset.decision = 'allow'; keep.dataset.decision = 'keep';
    allow.dataset.technical = String(technical);
    allow.dataset.stale = keep.dataset.stale = String(stale);
    allow.disabled = technical || stale || !!mutation; keep.disabled = stale || !!mutation;
    if (stale) form.append(el('p', 'This is an earlier occurrence. Its evidence is read-only; choose the current cut to change its decision.', 'prr-muted'));
    if (technical) {
      const why = el('p', 'This is a technical rejection. Editorial approval cannot make an invalid or missing recording usable. The technical problem must be repaired.', 'prr-muted');
      why.id = 'prr-technical-why'; allow.setAttribute('aria-describedby', why.id); form.append(why);
    }
    actions.append(allow, keep); form.append(actions, result); detail.append(form);
    async function vote(action) {
      if (mutation || stale) return;
      const id = row.id; const token = selection;
      mutation = 'decision'; paintMutations();
      allow.disabled = true; keep.disabled = true; say(result, 'Saving your review…');
      try {
        const body = {action, note: note.value, expected_revision: row.revision};
        if (reviewOccurrence(row)) body.expected_event_seq = reviewOccurrence(row);
        const response = await request(BASE + '/' + encodeURIComponent(id), {method: 'POST', body: JSON.stringify(body)});
        if (response.ok === false) throw new Error(response.error || response.detail || 'Review was not saved.');
        if (!dialog || token !== selection) return;
        const updated = response.row || await get(reviewDetailPath(id, reviewOccurrence(row)));
        if (!dialog || token !== selection) return;
        row = updated;
        if (status === 'pending' && updated.review_status !== 'pending') rows.delete(id);
        else if (rows.has(id)) rows.set(id, {...rows.get(id), ...updated});
        paintQueue(); paintDetail(updated, note.value);
        say(detail.querySelector('.prr-review-result'), response.effect?.say || updated.effect?.say || 'Review saved. No playback was requested.');
        poll();
      } catch (error) {
        if (dialog && token === selection) say(result, 'Review not confirmed: ' + error.message + '. Refresh this record before retrying if another reviewer changed it.', true);
      } finally {
        mutation = ''; paintMutations();
      }
    }
    section(detail, 'Original source — full text', row.source, true);
    section(detail, 'Writing → recording context', row.context, true);
    if (row.history) {
      const history = section(detail, 'Occurrence history', row.history);
      if (row.history_has_more && row.history_next_before) {
        let before = row.history_next_before;
        const older = button('Load earlier occurrences', async () => {
          older.disabled = true;
          try {
            const data = await get(BASE + '/' + encodeURIComponent(row.id) + '?limit=100&before=' + encodeURIComponent(before));
            history.insertBefore(el('pre', asText(data.history)), older);
            before = data.history_next_before; older.hidden = !data.history_has_more || !before;
          } catch (error) { say(result, error.message, true); }
          finally { older.disabled = false; }
        }); history.append(older);
      }
    }
    detail.append(button('Refresh this record', () => select(row.id, selectedEvent)));
    installWorkbench(row);
  }

  function labState(row) {
    const eventSeq = selectedEvent || reviewOccurrence(row), key = row.id + ':' + eventSeq;
    let state = workbenches.get(key);
    if (!state) {
      state = {key, id:row.id, eventSeq, row, tab:'review', data:null, loading:false, error:'', feedback:'',
        message:'', candidate:row.candidate || '', instruction:'', futureDraft:null, futureEnabled:true,
        request:null, lastRequest:null, operation:null, timer:null, version:0, loaded:false, selectedTrial:null, stale:false, posting:false, traceId:''};
      try { state.request = JSON.parse(sessionStorage.getItem('pine-review-lab:' + location.origin + ':' + key) || 'null'); }
      catch (_) { /* drafts and request identity still survive a panel close in memory */ }
      workbenches.set(key, state);
    }
    state.row = row;
    return state;
  }
  function rememberLab(state) {
    try {
      const key = 'pine-review-lab:' + location.origin + ':' + state.key;
      if (state.request) sessionStorage.setItem(key, JSON.stringify(state.request)); else sessionStorage.removeItem(key);
    } catch (_) { /* retain exact pending body in this controller */ }
  }
  function labVisible(state) { return !!detail && selected === state.id && selectedEvent === state.eventSeq; }
  function labPath(state, suffix = 'workbench') {
    return BASE + '/' + encodeURIComponent(state.id) + '/' + suffix;
  }
  function labHistorical(state) { return state.row.read_only === true || state.row.occurrence_current === false || state.data?.read_only === true || state.data?.occurrence_current === false; }
  function labRevision(state) { return Math.max(Number(state.row.revision) || 0, Number(state.data?.revision) || 0); }
  function installWorkbench(row) {
    const state = labState(row);
    const original = el('div', null, 'prr-review-pane');
    while (detail.children.length > 2) original.append(detail.children[2]);
    const tabs = el('div', null, 'prr-detail-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Review tools');
    for (const [name, title] of [['review','Review'],['discuss','Discuss'],['trace','Trace'],['try','Try wording']]) {
      const tab = button(title, () => showLabTab(state, name)); tab.dataset.labTab = name;
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'prr-lab-' + name); tabs.append(tab);
      tab.onkeydown = event => {
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault(); const all = [...tabs.children], i = all.indexOf(tab);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? all.length - 1 : (i + (event.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
        all[next].click(); all[next].focus();
      };
    }
    original.id = 'prr-lab-review'; original.setAttribute('role', 'tabpanel');
    const workspace = el('div', null, 'prr-workbench'); workspace.setAttribute('role', 'tabpanel');
    detail.append(tabs, original, workspace);
    showLabTab(state, state.tab);
  }
  function showLabTab(state, tab) {
    state.tab = tab;
    if (!labVisible(state)) return;
    detail.querySelector('.prr-review-pane').hidden = tab !== 'review';
    const workspace = detail.querySelector('.prr-workbench'); workspace.hidden = tab === 'review'; workspace.id = 'prr-lab-' + tab;
    detail.querySelectorAll('[data-lab-tab]').forEach(node => {
      const active = node.dataset.labTab === tab; node.setAttribute('aria-selected', String(active)); node.tabIndex = active ? 0 : -1;
    });
    if (tab !== 'review') {
      paintWorkbench(state);
      if (!state.loaded && !state.loading) void loadWorkbench(state);
    }
  }
  async function loadWorkbench(state, page = null) {
    if (disposed || state.loading || !state.eventSeq) return;
    state.loading = true; const version = ++state.version;
    try {
      const params = new URLSearchParams({event_seq:String(state.eventSeq)});
      if (state.traceId) params.set('trace_id',state.traceId);
      if (page) params.set(page.name + '_before', page.before);
      const data = await get(labPath(state) + '?' + params);
      if (disposed || version !== state.version) return;
      if (String(data.review_id) !== state.id || Number(data.event_seq) !== state.eventSeq) throw new Error('The server returned another occurrence. Reopen the intended cut.');
      // Older requests cannot replace the policy/review revision already shown.
      if (Number(data.revision) < labRevision(state)) { state.stale = true; state.error = 'This view changed. Refresh the record before applying a fix.'; return; }
      if (page && state.data) {
        const seen = new Set(); const all = [...workbenchItems(state.data[page.name]), ...workbenchItems(data[page.name])];
        data[page.name] = {...data[page.name], items:all.filter(item => { const key = item.id || item.seq; if (seen.has(key)) return false; seen.add(key); return true; })};
        for (const name of ['messages','trace','trials']) if (name !== page.name) data[name] = state.data[name];
      }
      state.data = data; state.loaded = true; state.stale = false; state.error = '';
      if (state.futureDraft == null) { state.futureDraft = data.settings?.crystal_instruction || ''; state.futureEnabled = data.settings?.enabled !== false; }
      const operations = data.operations || [];
      const matched = operations.find(op => op.id === state.operation?.id || (state.request && (op.id === state.request.operation_id || op.request_id === state.request.body.request_id || op.id === state.request.body.request_id)));
      const active = matched || operations.find(workbenchPending);
      if (active) state.operation = active;
      if (state.operation && !workbenchPending(state.operation)) {
        const op = state.operation;
        const failed = op.lease_expired === true || ['failed','lease_expired','expired'].includes(op.status);
        state.feedback = failed ? 'The request failed: ' + asText(op.error || 'No result was saved.')
          : op.result?.effect?.say || op.result?.say || (op.kind === 'apply' ? 'The apply request finished. Inspect the saved outcome below.' : 'Saved with this occurrence.');
        if (failed) state.error = state.feedback;
        if (state.request && !state.posting) { state.lastRequest = failed ? state.request : null; state.request = null; rememberLab(state); }
        if (mutation === 'lab' && labMutationKey === state.key && !state.posting) mutation = '';
      } else if (active && workbenchPending(active)) {
        mutation = 'lab'; labMutationKey = state.key;
        if (!state.posting) state.feedback = 'The orchestrator is working on a saved ' + ({discuss:'discussion',try:'wording trial',apply:'wording application',accept:'operator acceptance'}[active.kind] || 'diagnostic') + ' request. You can close this panel and return.';
      }
    } catch (error) {
      if (error.name !== 'AbortError') state.error = 'Workbench unavailable: ' + error.message;
    } finally {
      state.loading = false;
      if (mutation === 'lab' && labMutationKey === state.key && !state.posting && !workbenchPending(state.operation)) mutation = '';
      paintWorkbench(state); paintMutations();
      clearTimeout(state.timer);
      if (!disposed && workbenchPending(state.operation)) state.timer = setTimeout(() => loadWorkbench(state), 1500);
    }
  }
  async function sendLab(state, kind, fields, retry = false) {
    const requestedKind = retry ? state.request?.kind : kind;
    if (disposed || state.stale || (labHistorical(state) && !(requestedKind === 'discuss' && state.data?.capabilities?.discuss === true)) || (!retry && (mutation || state.request))) return;
    if (retry && (mutation || !state.request)) return;
    if (!state.eventSeq || !state.loaded) return;
    if (!retry) { state.operation = null; state.request = {kind, body:{event_seq:state.eventSeq, expected_revision:labRevision(state), ...fields, request_id:newBatchId()}}; }
    const attempt = state.request;
    state.posting = true; state.lastRequest = null; rememberLab(state); mutation = 'lab'; labMutationKey = state.key; state.error = ''; state.feedback = 'Submitting ' + label(attempt.kind) + '…'; paintWorkbench(state); paintMutations();
    try {
      const data = await request(labPath(state, attempt.kind), {method:'POST', body:JSON.stringify(attempt.body)});
      if (data.ok === false) throw new Error(data.error || data.detail || 'The request was not confirmed.');
      if (!data.operation?.id) throw new Error('The server did not confirm an operation ID.');
      state.operation = data.operation; attempt.operation_id = data.operation.id; rememberLab(state);
      state.feedback = workbenchPending(data.operation) ? 'The orchestrator is working. You can close this panel and return.' : 'Request saved.';
      if (requestedKind === 'discuss' && state.message === attempt.body.message) state.message = '';
      state.posting = false;
      await loadWorkbench(state);
    } catch (error) {
      state.error = 'Request not confirmed: ' + error.message + '. Retry uses the same request; it will not start a second operation.';
      if (labMutationKey === state.key) mutation = '';
    } finally { state.posting = false; paintWorkbench(state); paintMutations(); }
  }
  function paintWorkbench(state) {
    if (!labVisible(state) || state.tab === 'review') return;
    const target = detail.querySelector('.prr-workbench'); if (!target) return;
    const focused = target.contains(document.activeElement) ? document.activeElement : null;
    const focus = focused?.dataset.labField, caret = focused?.selectionStart != null ? [focused.selectionStart, focused.selectionEnd] : null;
    const oldLog = target.querySelector('.prr-chat-log');
    const chatPosition = oldLog ? {top:oldLog.scrollTop,atEnd:oldLog.scrollHeight-oldLog.scrollTop-oldLog.clientHeight<24} : null;
    target.replaceChildren();
    const scope = el('p', 'Occurrence ' + state.eventSeq + ' · ' + (labHistorical(state) ? 'Historical evidence · read-only' : 'Discussion and trials do not play audio.'), 'prr-lab-scope'); target.append(scope);
    const feedback = el('p', state.error || state.feedback || (state.loading ? 'Loading saved work…' : ''), 'prr-lab-result');
    feedback.setAttribute('role','status'); feedback.classList.toggle('prr-error', !!state.error); target.append(feedback);
    if (!state.eventSeq) { target.append(el('p','This record has no occurrence identity. Reopen a current notification to use these tools.')); return; }
    const refresh = button('Refresh saved work', () => loadWorkbench(state)); refresh.dataset.lab = 'refresh'; refresh.disabled = state.loading; target.append(refresh);
    if (state.request && !workbenchPending(state.operation)) {
      const retry = button('Retry same request', () => sendLab(state, state.request.kind, {}, true)); retry.dataset.lab = 'retry'; retry.disabled = !!mutation || state.stale || (labHistorical(state) && state.request.kind !== 'discuss'); target.append(retry);
    }
    const locked = state.stale || !state.loaded || !!state.request;
    function action(text, kind, fn, unavailable = false) {
      const node = button(text, fn, (kind === 'apply' || kind === 'accept') ? 'prr-primary' : ''); node.dataset.lab = kind; node.dataset.labMutation = kind;
      const historical = labHistorical(state) && !(kind === 'discuss' && state.data?.capabilities?.discuss === true) && kind !== 'settings';
      node.dataset.unavailable = String(locked || historical || unavailable); node.disabled = !!mutation || locked || historical || unavailable; return node;
    }
    function field(title, name, value, setter, rows = 3) {
      const wrap = el('label', title, 'prr-lab-field'); const input = el('textarea'); input.rows = rows; input.value = value; input.dataset.labField = name;
      input.oninput = () => setter(input.value); wrap.append(input); target.append(wrap); return input;
    }
    function earlier(name, container = target) {
      const part = state.data?.[name]; if (part?.has_more && part.next_before != null) {
        const more = button('Load earlier ' + name, () => loadWorkbench(state, {name,before:part.next_before})); more.dataset.labMore = name; more.disabled = state.loading; container.append(more);
      }
    }
    if (state.lastRequest) {
      const previous = state.lastRequest;
      const fields = {...previous.body}; delete fields.request_id; delete fields.event_seq; delete fields.expected_revision;
      target.append(action('Start a new attempt', previous.kind, () => {state.operation=null;return sendLab(state,previous.kind,fields);}));
    }
    if (state.tab === 'discuss') {
      const log = el('div', null, 'prr-chat-log'); log.setAttribute('role','log'); log.setAttribute('aria-label','Discussion with the orchestrator');
      const messages = workbenchItems(state.data?.messages).slice().sort((a,b) => Number(a.seq) - Number(b.seq));
      for (const item of messages) {
        const message = el('article', null, 'prr-chat-message'); message.dataset.role = item.role;
        message.append(el('strong', item.role === 'user' ? 'You' : item.role === 'assistant' ? 'Orchestrator' : label(item.role)), el('p', asText(item.content)));
        log.append(message);
      }
      if (!messages.length) log.append(el('p','Ask why the line was cut, inspect the decision, or discuss a possible repair. Saved replies stay with this occurrence.','prr-muted'));
      const input = field('Message to the orchestrator', 'message', state.message, value => { state.message = value; }, 3);
      input.placeholder = 'What caused this cut, and what would fix it?';
      const send = action('Send message', 'discuss', () => { if (state.message.trim()) void sendLab(state,'discuss',{message:state.message}); });
      input.onkeydown = event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); send.click(); } };
      target.append(send, el('p','Ctrl/⌘ + Enter sends. Discussion does not approve a line or change station settings.','prr-muted'));
      target.append(el('h4','Saved discussion'),log); earlier('messages');
      log.scrollTop = chatPosition && !chatPosition.atEnd ? chatPosition.top : log.scrollHeight;
    } else if (state.tab === 'trace') {
      target.append(el('h4','Prompt and workflow evidence'));
      target.append(button('Edit future crystal instruction',()=>{const editor=target.querySelector('.prr-lab-settings');editor.open=true;editor.scrollIntoView({block:'nearest'});editor.querySelector('textarea').focus();}));
      const traceSources = state.data?.trace_sources || [];
      if (traceSources.length) {
        const choice = el('label','Inspected run ', 'prr-trace-choice'); const select = el('select'); select.dataset.lab = 'trace-source'; select.setAttribute('aria-label','Inspected prompt run');
        const original = el('option','Original cut evidence'); original.value=''; select.append(original);
        for (const source of traceSources) { const option=el('option',source.label || source.id); option.value=source.id; select.append(option); }
        select.value = state.traceId; select.disabled=state.loading;
        select.onchange = () => {state.traceId=select.value;state.data.trace={items:[],note:'Loading the selected run…'};paintWorkbench(state);void loadWorkbench(state);};
        choice.append(select); target.append(choice);
      }
      const trace = state.data?.trace;
      target.append(el('p', trace?.note || 'Only retained evidence is shown. Missing original prompts are identified explicitly.', 'prr-muted'));
      for (const item of workbenchItems(trace)) {
        const record = item.record || item;
        section(target, [label(record.stage || record.event || 'Trace'), record.attempt != null ? 'attempt ' + record.attempt : '', record.provenance?.origin || record.provenance?.kind || ''].filter(Boolean).join(' · '), item, true);
      }
      if (state.loaded && !workbenchItems(trace).length) target.append(el('p','No original prompt trace was captured for this occurrence.','prr-muted'));
      earlier('trace');
      section(target,'Recorded workflow and gate', state.row.system_path || {gate:state.row.gate,context:state.row.context}, true);
      section(target,'Observed pipeline diagnostics', state.data?.diagnostics || 'Unavailable', false);
      const settings = el('details', null, 'prr-section prr-lab-settings'); settings.append(el('summary','Future crystal instruction'));
      settings.append(el('p','This changes future crystal prompts. It does not rewrite this line or apply a trial.'));
      const enable = el('label'); const enabled = el('input'); enabled.type = 'checkbox'; enabled.checked = state.futureEnabled; enabled.dataset.labField = 'future-enabled'; enabled.onchange = () => {state.futureEnabled = enabled.checked;}; enable.append(enabled,document.createTextNode(' Use the saved instruction'));
      const instruction = el('textarea'); instruction.rows = 5; instruction.value = state.futureDraft || ''; instruction.dataset.labField = 'future'; instruction.setAttribute('aria-label','Future crystal instruction'); instruction.oninput = () => {state.futureDraft = instruction.value;};
      const save = action('Save future crystal instruction','settings',async () => {
        if (mutation || !state.data?.settings) return;
        mutation = 'lab-settings'; paintMutations();
        try {
          const result = await request('/api/orchestrator/rejection-lab/settings',{method:'POST',body:JSON.stringify({expected_revision:state.data.settings.revision,crystal_instruction:state.futureDraft,enabled:state.futureEnabled})});
          if (result.ok === false) throw new Error(result.error || result.detail || 'Settings not saved.');
          state.data.settings = result.settings || result; state.feedback = 'Future crystal instruction saved. This line and its trial were not applied.'; state.error = '';
        } catch(error) { state.error = 'Instruction not saved: ' + error.message + '. Refresh saved work before retrying; your draft is retained.'; }
        finally {mutation = ''; paintWorkbench(state); paintMutations();}
      }, !state.data?.settings);
      settings.append(enable,instruction,save); target.append(settings);
    } else if (state.tab === 'try') {
      target.append(el('p','Test revised wording against the real gate. A trial preserves its machine report; applying it is a separate action.'));
      const capabilities = state.data?.capabilities || {};
      if (capabilities.try_wording === false) target.append(el('p',capabilities.reason || capabilities.try_wording_reason || 'Wording trials are not supported for this gate. Discussion and retained trace are still available.','prr-muted'));
      if (capabilities.apply_wording === false && capabilities.apply_reason) target.append(el('p',capabilities.apply_reason,'prr-muted'));
      field('Candidate wording · leave blank to request a rewrite', 'candidate', state.candidate, value => {state.candidate=value;}, 6);
      field('Instruction for this trial (optional)', 'instruction', state.instruction, value => {state.instruction=value;}, 3);
      target.append(action('Preview trial','try',()=>sendLab(state,'try',{candidate:state.candidate,instruction:state.instruction}),capabilities.try_wording !== true));
      // 2026-09-08: the operator's wording goes through with the operator's
      // authority. The machine report is recorded, never a gate; the
      // instruction becomes a standing lesson for lines of this kind.
      target.append(action('Approve as written','accept',()=>sendLab(state,'accept',{candidate:state.candidate,instruction:state.instruction}),capabilities.apply_wording !== true || !String(state.candidate || '').trim()));
      target.append(el('p','Approve as written applies YOUR wording to this line and records it for recovery, whatever the machine checks say. The instruction above is kept as a standing lesson for lines of this kind, and this source/wording pair is approved outright from now on.','prr-muted'));
      const trials = workbenchItems(state.data?.trials);
      for (const trial of trials) {
        const card = el('article',null,'prr-trial'); card.dataset.trialId = trial.id;
        card.append(el('h4','Trial ' + (trial.seq || trial.id)), el('pre',asText(trial.candidate)));
        const passed = trial.evaluation?.ok === true;
        card.append(el('p',passed ? 'Acceptance checks passed for this trial. Apply checks the current rules again.' : 'This trial did not pass the acceptance checks. Edit the wording and preview another trial.', passed ? 'prr-muted' : 'prr-error'));
        const editorial = trial.evaluation?.tint?.editorial;
        if(editorial?.accepted_with_advisories) card.append(el('p','Accepted in fluid mode with style advisories: '+(editorial.advisory_faults || []).join('; ')+'. The raw machine report remains below.','prr-muted'));
        section(card,'Original and previous wording',trial.baseline);
        section(card,'Machine evaluation · unchanged',trial.evaluation,true);
        section(card,'Trial prompt and provenance',trial.provenance);
        if (trial.effect) section(card,'Saved apply result',trial.effect,true);
        const actions = el('div',null,'prr-actions');
        actions.append(button('Edit this trial',()=>{state.candidate=trial.candidate || '';state.selectedTrial=trial.id;paintWorkbench(state);}));
        actions.append(action('Apply wording to recording','apply',()=>sendLab(state,'apply',{trial_id:trial.id}),capabilities.apply_wording !== true || !passed || trial.applyable === false || trial.applicable === false));
        if (!passed) actions.append(action('Approve as written','accept',()=>sendLab(state,'accept',{candidate:trial.candidate || '',instruction:trial.provenance?.instruction || state.instruction || ''}),capabilities.apply_wording !== true || !String(trial.candidate || '').trim()));
        card.append(actions,el('p','Apply queues only this tested wording through normal recovery. It does not play audio.','prr-muted')); target.append(card);
      }
      if (state.loaded && !trials.length) target.append(el('p','No saved trials for this occurrence.','prr-muted'));
      earlier('trials');
    }
    if (state.operation && !workbenchPending(state.operation)) section(target,'Last operation result',state.operation,true);
    paintMutations();
    if (focus) {
      const replacement = [...target.querySelectorAll('[data-lab-field]')].find(node => node.dataset.labField === focus);
      replacement?.focus(); if (caret && replacement?.setSelectionRange) replacement.setSelectionRange(...caret);
    }
  }
  async function room() {
    const target = panel?.querySelector('.prr-room'); if (!target) return;
    target.replaceChildren(el('p', 'Loading writing and recording context…'));
    try {
      const data = await get(BASE + '/context');
      if (!dialog || !target.isConnected) return;
      target.replaceChildren();
      if (data.route) section(target, 'Writing → on-air path', Array.isArray(data.route) ? data.route.join('\n') : data.route, true);
      section(target, 'Writing room', data.writing, true);
      section(target, 'Recording room', data.recording, true);
      section(target, 'Tint and evaluation', data.tint, true);
      if (data.orchestrator) section(target, 'Current orchestrator decisions and schedule', data.orchestrator);
      if (data.technical_note) target.append(el('p', data.technical_note, 'prr-muted'));
    } catch (error) { if (target.isConnected) target.replaceChildren(el('p', error.message, 'prr-error')); }
  }
  function close() {
    if (!dialog) return;
    ++selection; ++listVersion; policyDirty = false;
    dialog.close(); dialog.remove(); dialog = panel = queue = detail = count = null;
    for (const controller of reads) controller.abort();
    if (returnFocus?.isConnected) returnFocus.focus();
  }
  async function open(id, eventSeq = null) {
    if (id && typeof id === 'object') { eventSeq = reviewOccurrence(id); id = id.id || id.review_id; }
    if (disposed) return;
    dismissNotice();
    if (dialog) { if (id) await select(id, eventSeq); return; }
    const openingSelection = selection;
    returnFocus = document.activeElement;
    dialog = el('dialog', null, 'prr-dialog'); dialog.dataset.rejectionReview = 'dialog';
    dialog.setAttribute('aria-labelledby', 'prr-title');
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    panel = el('div', null, 'prr-panel');
    const header = el('header', null, 'prr-header'); const title = el('div', null, 'prr-title-block');
    title.append(el('h2', 'Rejected lines')); title.firstChild.id = 'prr-title'; count = el('p', '', 'prr-muted'); title.append(count);
    const links = el('div', null, 'prr-actions');
    if (hooks.onLogic) links.append(button('Decision graph', () => { close(); hooks.onLogic(); }));
    if (hooks.onFlow) links.append(button('Station flow', () => { close(); hooks.onFlow(); }));
    links.append(button('Close', close)); header.append(title, links); panel.append(header);
    const quick = el('section', null, 'prr-quick-controls'); quick.setAttribute('aria-label', 'Rejection system and current batch');
    const masterArea = el('div', null, 'prr-master-control');
    const master = button('', () => savePolicy(true), 'prr-master-switch'); master.dataset.policy = 'master';
    master.setAttribute('role', 'switch'); master.setAttribute('aria-label', 'Rejection system');
    master.setAttribute('aria-checked', String(policy?.enabled !== false));
    master.append(el('span', 'Rejection system'), el('span', '', 'prr-switch-track'), el('strong', policy?.enabled === false ? 'Off' : 'On', 'prr-switch-value'));
    const masterResult = el('p', '', 'prr-master-result'); masterResult.setAttribute('role', 'status');
    masterArea.append(master);
    const batchArea = el('div', null, 'prr-batch-control');
    const approve = button('Approve all', approveCurrent, 'prr-primary'); approve.dataset.review = 'approve-current';
    const batchHelp = el('p', 'One time: approve eligible pending lines across all pages and gates. Later rejections stay unchanged. Technical or incomplete records remain available for review.', 'prr-batch-help');
    batchHelp.id = 'prr-batch-help'; approve.setAttribute('aria-describedby', batchHelp.id);
    const batchResult = el('p', batchFeedback.text || (batchRequestId ? 'A prior approval request is unconfirmed. Retry checks the same request to avoid approving a second batch.' : ''), 'prr-batch-result');
    batchResult.classList.toggle('prr-error', batchFeedback.error);
    batchResult.setAttribute('role', 'status'); batchArea.append(approve);
    quick.append(masterArea, batchArea); header.insertBefore(quick, links);
    const help = el('div', null, 'prr-review-help'); help.append(batchHelp, masterResult, batchResult); panel.append(help);
    const connection = el('p', 'Reviewing does not play or replay audio.', 'prr-connection'); connection.setAttribute('role', 'status'); panel.append(connection);
    const learner=el('details',null,'prr-learning');learner.dataset.learningPanel='';learner.open=learning.open;
    const learnerTitle=el('summary','Learn and improve');learnerTitle.append(el('span','','prr-learning-caption'));
    learner.append(learnerTitle,el('div',null,'prr-learning-body'));
    learner.ontoggle=()=>{learning.open=learner.open;if(learner.open&&!learning.data&&!learning.loading)void loadLearning();};
    panel.append(learner);paintLearning();
    const controls = el('details', null, 'prr-policy'); controls.append(el('summary', 'Rejection controls'));
    controls.append(el('p', '', 'prr-policy-state'));
    const threshold = el('label'); threshold.append(el('span', 'Allow up to 0 editorial flags', 'prr-policy-caption'));
    const number = el('input'); number.type = 'number'; number.min = '0'; number.max = '10'; number.step = '1'; number.dataset.policy = 'max_faults';
    number.setAttribute('aria-label', 'Editorial flags allowed');
    number.oninput = () => { policyDirty = true; panel.querySelector('.prr-policy-caption').textContent = 'Allow up to ' + number.value + ' editorial flags'; };
    threshold.append(number); controls.append(threshold);
    const gatePolicy = el('div', null, 'prr-gate-policy'); controls.append(gatePolicy);
    const save = button('Save allowance and gates', () => savePolicy()); save.dataset.policy = 'save';
    const policyActions = el('div', null, 'prr-actions'); policyActions.append(save); controls.append(policyActions);
    const policyResult = el('p', '', 'prr-policy-result'); policyResult.setAttribute('role', 'status'); controls.append(policyResult); panel.append(controls);
    const overview = el('details', null, 'prr-overview'); overview.append(el('summary', 'Writing and recording room overview'));
    overview.append(button('Refresh room overview', room), el('div', null, 'prr-room'));
    overview.ontoggle = () => { if (overview.open && !overview.querySelector('.prr-room').childNodes.length) room(); }; panel.append(overview);
    const body = el('div', null, 'prr-body'); const sidebar = el('nav', null, 'prr-sidebar'); sidebar.setAttribute('aria-label', 'Rejected line queue');
    const filters = el('div', null, 'prr-filters');
    for (const [name, values] of [['status', [['pending','Awaiting review'],['all','All decisions']]], ['gate', [['','All gates']]]]) {
      const select = el('select'); select.dataset.filter = name; select.setAttribute('aria-label', name === 'status' ? 'Review status' : 'Rejection gate');
      for (const [value, text] of values) { const option = el('option', text); option.value = value; select.append(option); }
      select.value = name === 'status' ? status : gate;
      select.onchange = () => { if (name === 'status') status = select.value; else gate = select.value; loadQueue(true); };
      filters.append(select);
    }
    queue = el('div', null, 'prr-queue'); const more = button('Load earlier lines', () => loadQueue(false, true), 'prr-more'); more.hidden = true;
    sidebar.append(filters, button('Refresh queue', () => loadQueue(true)), queue, more); detail = el('article', null, 'prr-detail'); detail.setAttribute('aria-label', 'Complete rejection record');
    detail.append(el('p', 'Choose a line to read the original, the candidate and the complete decision.', 'prr-empty'));
    body.append(sidebar, detail); panel.append(body); dialog.append(panel); document.body.append(dialog); dialog.showModal();
    badge(); paintPolicy(); await loadQueue(true);
    if (id && dialog && openingSelection === selection) await select(id, eventSeq);
    try { const data = await get(POLICY); if (dialog && !policyDirty) { policy = data.policy || data; paintPolicy(); paintGates(); } } catch (_) { /* list carries policy too */ }
  }
  const controller = {open, poll, close, configure(value) { hooks = {...hooks, ...value}; if (value.request) request = value.request; },
    destroy() { disposed = true; clearTimeout(timer); for (const state of workbenches.values()) clearTimeout(state.timer); close(); dismissNotice(); for (const read of reads) read.abort(); this.destroyed = true; }, destroyed: false};
  window.PineRejectionReview = controller;
  // Dynamic import callers supply callbacks immediately; the first read starts
  // on the following task, never during script evaluation.
  timer = setTimeout(poll, 0);
  return controller;
}

if (typeof window !== 'undefined' && typeof window.api === 'function') create({request: window.api});
