/* THE SCRIPT VIEW, BUILT TO THE SKETCH.
 *
 * The operator numbered seven regions and said what each one is. They are
 * marked 1..7 through this file so the code and the drawing can be read
 * against each other:
 *
 *   1  back to the ordinary view          top-left, three small buttons
 *   2  a menu of every view
 *   3  reload / re-fit this view
 *   4  the pine tree - taps open a Pine Box panel
 *   5  the media player: art, spectrum, meter, a playhead you can scrub,
 *      and back/forward across tracks
 *   6  the live feed, "like an instant message correspondence", endless and
 *      auto-scrolling
 *   7  the right HALF of the screen: a Hollywood script of the broadcast,
 *      generated live, scrollable, tappable, editable, sendable back to the
 *      recording room
 *
 * WHERE THE SCRIPT COMES FROM, and why this is not a rendering of the feed.
 * #1050 already writes a real screenplay: GET /api/screenplay/{hour} returns
 * typed elements - scene, subheader, character, dialogue, parenthetical,
 * action, transition - with each dialogue carrying the aired line id, its
 * engine, whether it was tinted and its clip. Measured on the live station:
 * 127 elements for one hour, 63 of them dialogue. So this view FORMATS a
 * script the station already generates, rather than inventing one out of
 * chat rows, and the tap targets are real line ids that the rest of the
 * machinery already understands.
 *
 * THE TRAFFIC RULE. One shared feed subscription for the live half (the
 * ticker, the player, the console line) and ONE fetch of the screenplay,
 * refreshed on a slow clock and on demand. Nothing here polls at speed.
 * That rule is not decorative: 38 concurrent requests were measured
 * starving this tablet's audio for 46 seconds.
 */
(function (root) {
  'use strict';

  var HOST_CLASS = 'sp-page';
  var SCREENPLAY_REST_MS = 20000;   /* the script is minutes-scale news */
  /* The feed is the live working surface, not the permanent transcript.
     The screenplay and trace ledger retain every line; holding hundreds of
     completed rows here makes the tablet relayout a history nobody can see. */
  var FEED_MAX = 120;
  var FEED_EVENT_MAX = 48;

  var mounted = false;
  var host = null;
  var stop = null;
  var elements = [];
  var hourKey = '';
  var scriptNodes = new Map();      /* #1273: element id -> its live node */
  var lineNodes = new Map();        /* live line id -> mounted node */
  var paintedIn = null;             /* #1273: the box those nodes hang in */
  var chasedAt = 0;                 /* #1271: last re-read chased by a mark */
  var beforeKey = '';               /* #1276: the closed hour we hold */
  var beforePage = null;            /*         and its page, fetched once */
  /* #1269: the join between an element's id and its text. A character no
     id or text can contain, written as an ESCAPE - an earlier patch put a
     real NUL byte in this file, which every text tool then read as binary. */
  var SEP = '\u0000';
  var fetchedAt = 0;
  var fetching = false;
  var pinned = null;                /* the element the operator tapped */
  var stick = true;                 /* keep the script scrolled to the end */
  var feedStick = true;
  var seen = Object.create(null);   /* feed rows already drawn */
  var feedNodes = Object.create(null);  /* #1279: id -> its live row */
  var feedLive = '';                    /* #1279: the row marked airing */

  /* FOLLOWING THE LINE THAT IS ACTUALLY BEING SAID.
   *
   * "I need the currently spoken line that is being said to be the line
   * being highlighted... It is highlighting 20 lines."
   *
   * It was highlighting 71, and for a reason that had nothing to do with
   * speech: the amber marker went on any element whose `aired` was not the
   * string 'stream', and the screenplay's three values are 'published'
   * (59), 'stream' (43) and 'prepared' (12). 'published' means it ALREADY
   * AIRED. So the mark was on most of the hour.
   *
   * The live position is not in the screenplay at all - it is in the
   * station's `stream_now`: the epoch second the burst began, its length,
   * and every row's from/until offset inside it. That is enough to know
   * which line is in the room RIGHT NOW without asking, so the highlight
   * moves on a local 250 ms tick against a 4 s poll - the cadence the
   * codebase already prescribes ("the round clock every 250 ms,
   * speaking_now every 4 s"), and no extra traffic for a station with a
   * documented history of being starved by chatty clients. */
  var liveStream = null;            /* stream_now, as last polled */
  var speakingNow = null;           /* the 4 s fallback */
  var flow = null;                  /* dialogue_flow: why it is waiting */
  var stationPaused = false;
  var skewMs = 0;                   /* server clock minus ours */
  var lastOffMs = 0;                /* #1267: watched, no longer applied */
  var nowLineId = '';               /* the one line being said */
  var follow = true;                /* keep it on screen */
  var crawlStop = null;             /* the live strip can retake the pane */
  var selfScrollUntil = 0;          /* a scroll WE started, not the operator */
  var adrift = 0;                   /* #1282: consecutive off-screen reads */
  var folded = Object.create(null);   /* #1285: seg id -> folded? */
  var byHand = Object.create(null);   /* #1285: the operator said so */
  var liveSeg = '';                   /* #1285: the segment on air */
  var planHours = [];                 /* #1289: the director's entries */
  var bankPlan = null;                 /* read-ahead stock for the next two hours */
  var bankFetchedAt = 0;
  var planAt = 0;                     /* when we last read them */
  var planning = false;
  var planWay = 'below';              /* #1289: 'below' | 'beside' */
  var PLAN_REST_MS = 30000;           /* a running order is not news */
  var readinessPick = '';             /* upcoming slot open in the desk */
  var readinessPrint = '';            /* keep the operator's scroll/focus */
  var readinessClockAt = 0;
  var newsChoiceState = null;
  var liveCuePrint = '';               /* repaint only when the cue changes */
  var bandManager = null;
  var beat = 0;
  var rejectionItems = [];
  var rejectionFirstPage = [];
  var rejectionCursor = null;
  var rejectionHasMore = true;
  var rejectionLoading = false;
  var rejectionCount = 0;
  var rejectionHeadAt = 0;
  var rejectionLastStep = 0;
  var rejectionSelection = null;
  var rejectionDetail = null;
  var rejectionRequest = 0;
  var rejectionBusy = false;
  var rejectionLoadEpoch = 0;
  var rejectionPageRetryAt = 0;
  var rejectionPolicy = null;
  var rejectionTintState = null;
  var rejectionTintAt = 0;
  var rejectionTintPending = null;

  /* ------------------------------------------- THE ADMITTED CUE MAP
   *
   * "Render the committed sequence directly. Keep existing positions
   *  stable as new material is appended. Use the selected player's
   *  actual file and offset, mapped through its cue sheet, to identify
   *  the active occurrence."
   *
   * `admitMap` is the station's committed sequence as last polled - the
   * playout controller's own record, not a reconstruction from feed rows
   * and not the server's wall clock. `lastGood` is the last position this
   * view could TRUST, kept so a gap in the evidence shows the last true
   * mark rather than a guess or a blank.
   *
   * And `syncState` is published, because the audit is explicit that
   * hiding this would be the wrong cure: "Merely preventing a backward
   * visual movement would hide an audio fault; it would not enforce
   * playback order." */
  var admitMap = null;
  var lastGood = null;
  var syncState = 'held';
  var syncWhy = 'no playback evidence yet';
  var syncSince = 0;
  var syncRing = [];                  /* bounded: what the mark did, and why */
  var SYNC_RING_MAX = 240;
  var headWas = -1;                   /* the last READ position */
  var headMovedAt = 0;                /* and when it last actually moved */
  var STALL_MS = 8000;                /* read but motionless for this long */

  /* #1115: THE LAST ERRORS THIS PAGE SAW.
   *
   * A report about "the highlighted line is wrong" is worth little
   * without the throw that may have stranded the highlight - and by the
   * time the operator taps, the console that printed it is long gone
   * (on the tablet it was never visible at all: the WebView hides a
   * cross-origin throw behind "Script error."). So the page keeps its
   * own short ring, twelve entries, and ships it with every report. */
  var caught = [];

  function caughtNote(kind, what) {
    var msg = '';
    try {
      if (what && what.message) msg = String(what.message);
      else if (what && what.reason) {
        msg = String((what.reason && what.reason.message) || what.reason);
      } else msg = String(what);
    } catch (err) { msg = '(unprintable)'; }
    caught.push({at: Date.now(), kind: kind, msg: msg.slice(0, 200)});
    if (caught.length > 12) caught.splice(0, caught.length - 12);
  }
  try {
    if (typeof root.addEventListener === 'function') {
      root.addEventListener('error', function (ev) {
        caughtNote('error', (ev && ev.error && ev.error.message) ? ev.error : ev);
      });
      root.addEventListener('unhandledrejection', function (ev) {
        caughtNote('rejection', (ev && ev.reason) || ev);
      });
    }
  } catch (err) { /* an engine without listeners has no errors to keep */ }

  function api() { return root.pineDesktop || {get: function () { return Promise.reject(new Error('no bridge')); }}; }
  function el(id) { return document.getElementById(id); }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  var BAND_STORAGE_KEY = 'pine.script.bands.v1';
  var BAND_NAMES = {
    current: 'Current segment', sequence: 'Previous, on air and next',
    sync: 'In step with sound', readiness: 'Upcoming preparation'
  };

  function bandLoad() {
    var saved;
    try { saved = JSON.parse(root.localStorage.getItem(BAND_STORAGE_KEY) || '{}'); }
    catch (err) { saved = {}; }
    var state = {};
    Object.keys(BAND_NAMES).forEach(function (key) {
      state[key] = !!(saved && saved[key] === true);
    });
    return state;
  }

  function bandSave(state) {
    try { root.localStorage.setItem(BAND_STORAGE_KEY, JSON.stringify(state)); }
    catch (err) { /* private mode: controls remain usable */ }
  }

  function bandController(bands, toolbar, items) {
    var state = bandLoad();
    function apply() {
      var anyOpen = false, anyClosed = false;
      Object.keys(BAND_NAMES).forEach(function (key) {
        var item = items[key], closed = state[key];
        item.wrap.hidden = closed || (key === 'sequence' && item.content.hidden);
        item.restore.hidden = !closed;
        item.collapse.setAttribute('aria-expanded', String(!closed));
        item.restore.setAttribute('aria-expanded', String(!closed));
        if (closed) anyClosed = true;
        else if (!item.wrap.hidden) anyOpen = true;
      });
      bands.hidden = !anyOpen;
      /* Prompt History is a permanent Script command in this toolbar. Only
         the per-band restore buttons disappear when their bands are open. */
      toolbar.hidden = false;
    }
    function set(key, closed) {
      if (!Object.prototype.hasOwnProperty.call(items, key)) return;
      state[key] = !!closed;
      apply();
      bandSave(state);
    }
    apply();
    return {set: set, refresh: apply};
  }

  var REJECTION_PAGE = 24;
  var REJECTION_REFRESH_MS = 120000;

  function rejectionLabel(item) {
    var kind = String((item && (item.kind || item.gate)) || 'script').replace(/_/g, ' ');
    var reason = item && Array.isArray(item.reasons) && item.reasons.length
      ? String(item.reasons[0]) : 'Review needed';
    return kind + ': ' + reason;
  }

  function rejectionGlyph(item) {
    var kind = String((item && item.kind) || '').toLowerCase();
    if (kind.indexOf('call') >= 0) return '🎙️';
    if (kind.indexOf('music') >= 0) return '🎵';
    if (kind.indexOf('video') >= 0) return '🎬';
    if (kind.indexOf('news') >= 0) return '📰';
    return '📝';
  }

  function rejectionError(err) {
    return String((err && (err.message || err.detail)) || err || 'Request failed').slice(0, 180);
  }

  function rejectionPageItems(got) {
    if (!got || !Array.isArray(got.items)) throw new Error('Invalid review queue');
    return got.items.filter(function (item) {
      return item && item.id && item.review_status === 'pending';
    });
  }

  function rejectionListUrl(cursor) {
    return '/api/orchestrator/rejections?status=pending&limit=' + REJECTION_PAGE
      + (cursor ? '&before=' + encodeURIComponent(cursor) : '');
  }

  function rejectionBody(record, item, action, note) {
    var body = {note: note, expected_revision: record.revision,
      expected_event_seq: record.event_seq || record.latest_seq || item.event_seq};
    if (action !== 'note') body.action = action;
    return body;
  }

  function rejectionPolicyBody(policy) {
    var body = {enabled: policy.enabled === false};
    if (policy.revision != null) body.expected_revision = policy.revision;
    return body;
  }

  function contentGateBody(policy, gate, enabled) {
    var body = {expected_revision: policy.revision};
    if (gate === 'master') {
      body.master_enabled = enabled;
      body.gates = Object.fromEntries(Object.keys(policy.gates || {}).map(function (name) {
        return [name, false];
      }));
    }
    else body.gates = {[gate]: enabled};
    if (enabled) body.approval = 'enable';
    return body;
  }

  function contentGateEffective(policy, gate) {
    return !!(policy && policy.master_enabled && policy.gates
      && policy.gates[gate] === true);
  }

  function rejectionDirectorBody(item, record, note) {
    return {kind: String((record && record.context && record.context.kind) || '').trim(),
      text: String(note || '').trim(), scope: 'next', who: 'operator'};
  }

  function rejectionAppendWords(draft, words) {
    var addition = String(words || '').trim();
    var prior = String(draft || '').replace(/\s+$/, '');
    return addition ? prior + (prior ? ' ' : '') + addition : prior;
  }

  function rejectionTintSummary(state) {
    if (!state) return 'Current tint: checking station settings…';
    var known = state.crystals_on !== null && state.tint_share !== null;
    if (known && state.crystals_on === 0 && state.tint_share === 0) {
      return 'Current tint: off for new scripts · 0 active crystals · orchestrator share 0% · two-pass '
        + (state.two_pass === false ? 'off' : state.two_pass === true ? 'on' : 'unknown');
    }
    var parts = [];
    if (state.crystals_on !== null) parts.push(state.crystals_on + ' active crystal(s)');
    if (state.tint_share !== null) parts.push('orchestrator share ' + Math.round(state.tint_share * 100) + '%');
    if (state.two_pass !== null) parts.push('two-pass ' + (state.two_pass ? 'on' : 'off'));
    return 'Current tint: ' + (parts.length ? parts.join(' · ') : 'settings unavailable')
      + (known ? '' : ' · status incomplete');
  }

  function rejectionTintRead() {
    if (rejectionTintState && Date.now() - rejectionTintAt < 15000) return Promise.resolve(rejectionTintState);
    if (rejectionTintPending) return rejectionTintPending;
    rejectionTintPending = Promise.all([
      Promise.resolve(api().get('/api/tint')).catch(function () { return null; }),
      Promise.resolve(api().get('/api/orchestrator/logic')).catch(function () { return null; })
    ]).then(function (parts) {
      var tint = parts[0], logic = parts[1];
      var share = logic && logic.policy && logic.policy.tint_share;
      share = share && typeof share === 'object' ? share.value : share;
      share = share === undefined || share === null ? null : Number(share);
      rejectionTintState = {
        crystals_on: tint && Array.isArray(tint.crystals_on) ? tint.crystals_on.length : null,
        two_pass: tint && typeof tint.two_pass === 'boolean' ? tint.two_pass : null,
        tint_share: Number.isFinite(share) ? share : null,
        checked_at: new Date().toLocaleString(),
        sources: ['/api/tint', '/api/orchestrator/logic']
      };
      rejectionTintAt = Date.now();
      return rejectionTintState;
    }).finally(function () { rejectionTintPending = null; });
    return rejectionTintPending;
  }

  function rejectionTintPaint() {
    var summary = el('spReviewTintSummary');
    if (summary) summary.textContent = rejectionTintSummary(rejectionTintState);
    var evidence = el('spReviewTintEvidence');
    if (evidence) evidence.textContent = rejectionTintState
      ? JSON.stringify(rejectionTintState, null, 2) : 'Checking current station settings…';
  }

  function rejectionSay(message) {
    var node = el('spRejectCount');
    if (node) node.textContent = message;
  }

  function rejectionMarker(item) {
    var button = make('button', 'sp-reject-marker', rejectionGlyph(item));
    button.type = 'button';
    button.dataset.id = String(item.id);
    button.title = rejectionLabel(item);
    button.setAttribute('aria-label', 'Review ' + rejectionLabel(item));
    button.addEventListener('click', function () { rejectionOpen(item, button); });
    button.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      var peer = event.key === 'ArrowRight' ? button.nextElementSibling : button.previousElementSibling;
      if (peer) { event.preventDefault(); peer.focus(); }
    });
    return button;
  }

  function rejectionFill() {
    var track = el('spRejectTrack');
    if (!track) return;
    var viewport = el('spRejectViewport');
    var target = Math.min(64, Math.max(18, Math.ceil(((viewport && viewport.clientWidth) || 600) / 40) + 10));
    while (track.children.length < target && rejectionItems.length) {
      track.appendChild(rejectionMarker(rejectionItems.shift()));
    }
    if (rejectionItems.length < 8 && rejectionHasMore) rejectionLoad(false);
    if (!rejectionHasMore && !rejectionItems.length && rejectionFirstPage.length) {
      rejectionItems = rejectionFirstPage.slice();
    }
  }

  function rejectionLoad(head) {
    if (rejectionLoading || !mounted || !api().get) return;
    if (!head && !rejectionHasMore) return;
    if (!head && Date.now() < rejectionPageRetryAt) return;
    rejectionLoading = true;
    if (head) rejectionHeadAt = Date.now();
    var epoch = ++rejectionLoadEpoch;
    var url = rejectionListUrl(head ? null : rejectionCursor);
    Promise.resolve(api().get(url)).then(function (got) {
      if (!mounted || epoch !== rejectionLoadEpoch) return;
      var items = rejectionPageItems(got);
      if (head) {
        rejectionHeadAt = Date.now();
        rejectionFirstPage = items.slice();
        rejectionItems = items.slice();
        var track = el('spRejectTrack');
        if (track) track.replaceChildren();
        var viewport = el('spRejectViewport');
        if (viewport) viewport.scrollLeft = 0;
      } else {
        rejectionItems.push.apply(rejectionItems, items);
      }
      rejectionCursor = got.next_before || null;
      rejectionHasMore = !!got.has_more && !!rejectionCursor && items.length > 0;
      rejectionPageRetryAt = 0;
      rejectionCount = Number(got.unreviewed != null ? got.unreviewed : got.total) || 0;
      rejectionSay(rejectionCount ? rejectionCount + ' to review' : 'No pending reviews');
      rejectionFill();
    }).catch(function (err) {
      if (mounted && epoch === rejectionLoadEpoch) {
        rejectionPageRetryAt = Date.now() + 30000;
        rejectionSay('Review queue unavailable: ' + rejectionError(err));
      }
    }).finally(function () { if (epoch === rejectionLoadEpoch) rejectionLoading = false; });
  }

  function rejectionStep() {
    var viewport = el('spRejectViewport');
    var track = el('spRejectTrack');
    if (!viewport || !track) return;
    rejectionFill();
    if (!track.firstElementChild || rejectionSelection
        || (root.matchMedia && root.matchMedia('(hover: hover)').matches && viewport.matches(':hover'))
        || viewport.contains(document.activeElement)
        || (root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
      rejectionLastStep = Date.now();
      return;
    }
    var now = Date.now();
    if (!rejectionLastStep) { rejectionLastStep = now; return; }
    viewport.scrollLeft += Math.min(now - rejectionLastStep, 500) * 0.025;
    rejectionLastStep = now;
    var first = track.firstElementChild;
    if (track.children.length > 1 && first.offsetLeft + first.offsetWidth <= viewport.scrollLeft) {
      var width = first.offsetWidth + 6;
      first.remove();
      viewport.scrollLeft = Math.max(0, viewport.scrollLeft - width);
      rejectionFill();
    }
  }

  function buildRejectionStrip() {
    var strip = make('div', 'sp-reject-strip');
    strip.setAttribute('aria-label', 'Pending script reviews');
    var count = make('span', 'sp-reject-count', 'Reviews');
    count.id = 'spRejectCount';
    count.setAttribute('role', 'status');
    strip.appendChild(count);
    var viewport = make('div', 'sp-reject-viewport');
    viewport.id = 'spRejectViewport';
    viewport.setAttribute('role', 'group');
    viewport.setAttribute('aria-label', 'Script issues, scroll horizontally');
    var track = make('div', 'sp-reject-track');
    track.id = 'spRejectTrack';
    viewport.appendChild(track);
    strip.appendChild(viewport);
    var controls = make('button', 'sp-reject-controls', 'Review all / controls');
    controls.type = 'button';
    controls.title = 'Open all rejected lines and editorial controls';
    controls.addEventListener('click', rejectionControlsOpen);
    strip.appendChild(controls);
    return strip;
  }

  function rejectionPolicyOpen() {
    var overlay = el('spRejectionDetail');
    if (!overlay) return;
    rejectionRequest += 1;
    var selected = {controls: true};
    rejectionSelection = selected;
    rejectionDetail = null;
    overlay.hidden = false;
    overlay.parentElement.classList.add('sp-reviewing');
    overlay.replaceChildren();
    var back = make('button', 'sp-review-back', '← Live script');
    back.type = 'button';
    back.addEventListener('click', rejectionClose);
    overlay.appendChild(back);
    overlay.appendChild(make('h2', '', 'Content gates'));
    var feedback = make('p', 'sp-review-feedback', 'Loading gate policy...');
    feedback.id = 'spReviewPolicyFeedback';
    feedback.setAttribute('role', 'status');
    overlay.appendChild(feedback);
    var scroll = make('div', 'sp-review-scroll sp-gates-scroll');
    scroll.id = 'spContentGates';
    overlay.appendChild(scroll);
    back.focus();
    Promise.resolve(api().get('/api/orchestrator/content-gates')).then(function (got) {
      if (rejectionSelection !== selected) return;
      rejectionPolicy = got;
      rejectionPolicyRender();
    }).catch(function (err) { if (feedback.isConnected) feedback.textContent = 'Gate policy unavailable: ' + rejectionError(err); });
  }

  function rejectionPolicyRender(message) {
    var overlay = el('spRejectionDetail');
    if (!overlay || !rejectionSelection || !rejectionSelection.controls || !rejectionPolicy) return;
    var feedback = el('spReviewPolicyFeedback');
    var area = el('spContentGates');
    if (!area) return;
    var policy = rejectionPolicy;
    if (!policy.gates || !policy.inventory) {
      feedback.textContent = 'Gate policy response is incomplete.';
      return;
    }
    feedback.textContent = message || (policy.master_enabled
      ? 'Master gate enabled. Only individually enabled gates can reject content.'
      : 'Content gates off. Technical media checks still require repair.');
    area.replaceChildren();
    var all = make('button', 'sp-review-action sp-gates-all', 'Review all rejected lines');
    all.type = 'button';
    all.addEventListener('click', function () {
      var full = root.PineRejectionReview;
      if (full && typeof full.open === 'function') {
        rejectionClose();
        full.open(null);
        return;
      }
      var badge = document.querySelector('#desktopRejectionNotices > button.badge');
      if (badge) { rejectionClose(); badge.click(); return; }
      var first = document.querySelector('.sp-reject-marker');
      if (first) { rejectionClose(); first.click(); }
    });
    area.appendChild(all);
    area.appendChild(contentGateButton('master', 'Master content gate',
      'All editorial gates are bypassed while this is off.', policy.master_enabled));
    area.appendChild(make('p', 'sp-review-muted',
      'Technical checks are not editorial approvals. Missing or empty audio remains repair-only.'));
    var list = make('div', 'sp-gates-list');
    Object.keys(policy.inventory).forEach(function (gate) {
      var row = make('div', 'sp-gate-row');
      var info = make('div', 'sp-gate-info');
      info.appendChild(make('b', '', gate.replace(/_/g, ' ')));
      info.appendChild(make('span', '', String(policy.inventory[gate] || '')));
      var events = (policy.evidence || []).filter(function (entry) { return entry.gate === gate; });
      if (events.length) {
        var latest = events[events.length - 1];
        info.appendChild(make('small', '', 'Recent bypass: ' + String(latest.reason || '')
          + (latest.source ? ' (' + String(latest.source) + ')' : '')));
      }
      row.appendChild(info);
      row.appendChild(contentGateButton(gate, gate.replace(/_/g, ' '),
        'Explicitly enable this one editorial gate', policy.gates[gate] === true));
      row.appendChild(make('i', 'sp-gate-effective',
        contentGateEffective(policy, gate) ? 'active' : 'bypassed'));
      list.appendChild(row);
    });
    area.appendChild(list);
    var technical = make('div', 'sp-review-section');
    technical.appendChild(make('h3', '', 'Technical checks stay active'));
    technical.appendChild(make('p', 'sp-review-muted', (policy.technical_checks || []).join(' · ')));
    area.appendChild(technical);
  }

  function contentGateButton(gate, label, reason, on) {
    var button = make('button', 'sp-review-action sp-gate-toggle', on ? 'On' : 'Off');
    button.type = 'button';
    button.setAttribute('role', 'switch');
    button.setAttribute('aria-checked', String(on));
    button.setAttribute('aria-label', label + ': ' + (on ? 'on' : 'off'));
    button.title = reason;
    button.addEventListener('click', function () {
      if (!rejectionPolicy || button.disabled) return;
      if (!on && !button.dataset.confirm) {
        button.dataset.confirm = '1';
        button.textContent = 'Enable?';
        button.title = 'Press again to explicitly enable ' + label;
        return;
      }
      button.disabled = true;
      var selected = rejectionSelection;
      var feedback = el('spReviewPolicyFeedback');
      if (feedback) feedback.textContent = 'Saving ' + label + '...';
      var bridge = api();
      var write = bridge.patch || bridge.post;
      if (!write) {
        if (feedback) feedback.textContent = 'Station bridge cannot update gates.';
        button.disabled = false;
        return;
      }
      Promise.resolve(write.call(bridge, '/api/orchestrator/content-gates',
        contentGateBody(rejectionPolicy, gate, !on))).then(function (got) {
        if (!got || !got.gates || got.revision == null) throw new Error('Gate update was not confirmed');
        if (rejectionSelection !== selected) return;
        rejectionPolicy = got;
        rejectionPolicyRender(label + ' ' + (!on ? 'enabled' : 'disabled') + '.');
      }).catch(function (err) {
        if (feedback && feedback.isConnected) feedback.textContent = 'Gate unchanged: ' + rejectionError(err);
        button.disabled = false;
        button.textContent = on ? 'On' : 'Off';
        delete button.dataset.confirm;
      });
    });
    return button;
  }

  function rejectionControlsOpen() {
    rejectionPolicyOpen();
  }

  function rejectionEvidence(record) {
    return [
      ['Evaluation at rejection (historical)', record && record.evaluation],
      ['Technical flag at rejection (historical)', record && record.technical],
      ['System path at rejection (historical)', record && record.system_path]
    ];
  }

  function rejectionProfileView(record) {
    var check = record && record.profile_check;
    var stored = record && record.context && record.context.entry && record.context.entry.profile;
    if (!check || typeof check !== 'object') {
      return {compatible: null, stored: stored || null, current: null,
        compared: [], differences: [], ignored: [], impact: ''};
    }
    return {compatible: typeof check.compatible === 'boolean' ? check.compatible : null,
      stored: check.stored === undefined ? stored || null : check.stored,
      current: check.current === undefined ? null : check.current,
      compared: Array.isArray(check.compared_fields) ? check.compared_fields : [],
      differences: Array.isArray(check.differences) ? check.differences : [],
      ignored: Array.isArray(check.ignored_fields) ? check.ignored_fields : [],
      impact: String(check.impact || '')};
  }

  function rejectionProfileSection(record) {
    var profile = rejectionProfileView(record);
    var section = make('section', 'sp-review-section sp-review-profile');
    section.appendChild(make('h3', '', 'Writing profile comparison'));
    var status = make('p', 'sp-review-profile-status', profile.compatible === true
      ? 'Compatible with the current writing profile'
      : profile.compatible === false ? 'Writing profile differs from current settings'
        : 'Current profile comparison unavailable');
    status.dataset.compatible = String(profile.compatible);
    section.appendChild(status);
    var fields = make('dl', 'sp-review-profile-fields');
    [['Compared fields', profile.compared], ['Different fields', profile.differences],
      ['Ignored fields', profile.ignored]].forEach(function (part) {
      fields.appendChild(make('dt', '', part[0]));
      fields.appendChild(make('dd', '', part[1].length ? part[1].join(', ') : 'None reported'));
    });
    section.appendChild(fields);
    if (profile.impact) section.appendChild(make('p', 'sp-review-muted', profile.impact));
    var profiles = make('div', 'sp-review-columns');
    rejectionText(profiles, 'Stored writing profile', profile.stored);
    rejectionText(profiles, 'Current writing profile', profile.current);
    section.appendChild(profiles);
    return section;
  }

  function rejectionText(parent, label, value) {
    var box = make('section', 'sp-review-section');
    box.appendChild(make('h3', '', label));
    box.appendChild(make('pre', 'sp-review-text', value === undefined || value === null || value === ''
      ? 'Not available' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)));
    parent.appendChild(box);
  }

  function rejectionHistory(parent, label, rows) {
    var section = make('section', 'sp-review-section');
    section.appendChild(make('h3', '', label));
    if (!Array.isArray(rows) || !rows.length) {
      section.appendChild(make('p', 'sp-review-muted', 'No entries yet'));
    } else {
      var list = make('ol', 'sp-review-list');
      rows.forEach(function (row) {
        var at = row && (row.at || row.created_at || row.decided_at || row.time);
        var date = at ? new Date(typeof at === 'number' ? at * 1000 : at) : null;
        var when = date && !isNaN(date.getTime()) ? date.toLocaleString() : (at ? String(at) : '');
        var status = row && (row.action || row.status || row.review_status || row.event
          || row.kind || row.disposition || row.gate);
        var note = row && (row.note || row.reason || row.text || '');
        list.appendChild(make('li', '', [when, status, note].filter(Boolean).join(' · ')));
      });
      section.appendChild(list);
    }
    parent.appendChild(section);
  }

  function rejectionClose() {
    rejectionRequest += 1;
    if (rejectionSelection && rejectionSelection.micHoldTimer) {
      root.clearTimeout(rejectionSelection.micHoldTimer);
      rejectionSelection.micHoldTimer = null;
    }
    if (rejectionSelection && rejectionSelection.dictating && root.PineTalkDot
        && typeof root.PineTalkDot.cancelCapture === 'function') {
      root.PineTalkDot.cancelCapture();
    }
    var overlay = el('spRejectionDetail');
    if (overlay) overlay.hidden = true;
    var pane = overlay && overlay.parentElement;
    if (pane) pane.classList.remove('sp-reviewing');
    var marker = rejectionSelection && rejectionSelection.marker;
    rejectionSelection = null;
    rejectionDetail = null;
    rejectionPolicy = null;
    if (marker && marker.isConnected) marker.focus();
  }

  function rejectionRender() {
    var overlay = el('spRejectionDetail');
    var record = rejectionDetail;
    if (!overlay || !record) return;
    var previousScroll = overlay.querySelector('.sp-review-scroll');
    var scrollTop = previousScroll ? previousScroll.scrollTop : 0;
    var editing = document.activeElement && document.activeElement.id === 'spReviewNote';
    var selected = rejectionSelection;
    if (selected && selected.micHoldTimer) {
      root.clearTimeout(selected.micHoldTimer);
      selected.micHoldTimer = null;
    }
    var item = rejectionSelection && rejectionSelection.item || {};
    overlay.replaceChildren();
    var head = make('div', 'sp-review-head');
    var back = make('button', 'sp-review-back', '← Live script');
    back.type = 'button';
    back.addEventListener('click', rejectionClose);
    head.appendChild(back);
    head.appendChild(make('h2', '', 'Script review'));
    head.appendChild(make('span', 'sp-review-status', String(record.review_status || 'pending')));
    overlay.appendChild(head);
    var scroll = make('div', 'sp-review-scroll');
    scroll.appendChild(make('p', 'sp-review-meta', [item.kind, record.gate, record.disposition,
      record.occurrences && record.occurrences + ' occurrences'].filter(Boolean).join(' · ')));
    var tintSummary = make('p', 'sp-review-tint', rejectionTintSummary(rejectionTintState));
    tintSummary.id = 'spReviewTintSummary';
    scroll.appendChild(tintSummary);
    var reasons = make('section', 'sp-review-section');
    reasons.appendChild(make('h3', '', 'Why it was held then (historical)'));
    var reasonList = make('ul', 'sp-review-list');
    (Array.isArray(record.reasons) ? record.reasons : []).forEach(function (reason) {
      reasonList.appendChild(make('li', '', String(reason)));
    });
    if (!reasonList.children.length) reasonList.appendChild(make('li', '', 'No reason supplied'));
    reasons.appendChild(reasonList);
    scroll.appendChild(reasons);
    if (record.technical) scroll.appendChild(make('p', 'sp-review-warning',
      'Technical failure: repair the source or missing media. Editorial approval cannot make it playable.'));
    var texts = make('div', 'sp-review-columns');
    rejectionText(texts, 'Candidate', record.candidate || item.candidate_preview);
    rejectionText(texts, 'Source', record.source || item.source_preview);
    scroll.appendChild(texts);
    rejectionHistory(scroll, 'Notes', Array.isArray(record.notes) && record.notes.length
      ? record.notes : record.operator_notes || record.notes);
    rejectionHistory(scroll, 'History', record.history);
    rejectionHistory(scroll, 'Review decisions', Array.isArray(record.decisions)
      ? record.decisions.filter(function (entry) { return entry.action !== 'note'; }) : []);
    var evidence = make('details', 'sp-review-evidence');
    evidence.appendChild(make('summary', '', 'Checks and evidence'));
    var current = make('section', 'sp-review-section');
    current.appendChild(make('h3', '', 'Current tint settings'));
    var currentText = make('pre', 'sp-review-text', rejectionTintState
      ? JSON.stringify(rejectionTintState, null, 2) : 'Checking current station settings…');
    currentText.id = 'spReviewTintEvidence';
    current.appendChild(currentText);
    evidence.appendChild(current);
    evidence.appendChild(rejectionProfileSection(record));
    rejectionEvidence(record).forEach(function (part) {
      var section = make('section', 'sp-review-section');
      section.appendChild(make('h3', '', part[0]));
      var value = part[1];
      section.appendChild(make('pre', 'sp-review-text', value === undefined || value === null
        ? 'Not available for this cut' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)));
      evidence.appendChild(section);
    });
    scroll.appendChild(evidence);
    var editor = make('section', 'sp-review-section sp-review-editor');
    var composeHead = make('div', 'sp-review-compose-head');
    var label = make('label', '', 'Note or next-script direction');
    label.htmlFor = 'spReviewNote';
    composeHead.appendChild(label);
    var mic = make('button', 'sp-review-mic', '');
    mic.type = 'button';
    mic.title = 'Tap to dictate or stop; hold to send reply';
    mic.setAttribute('aria-label', mic.title);
    mic.setAttribute('aria-pressed', rejectionSelection.dictating ? 'true' : 'false');
    mic.innerHTML = folderIcon('c:microphone', '');
    mic.disabled = rejectionBusy;
    var held = false;
    var holdTimer = null;
    mic.addEventListener('pointerdown', function () {
      held = false;
      holdTimer = selected.micHoldTimer = root.setTimeout(function () {
        if (selected !== rejectionSelection) return;
        selected.micHoldTimer = null;
        held = true;
        if (selected.dictating) {
          selected.sendAfterDictation = true;
          root.PineTalkDot.finish();
        } else rejectionDirectNext();
      }, 450);
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (type) {
      mic.addEventListener(type, function () {
        if (holdTimer) root.clearTimeout(holdTimer);
        holdTimer = null;
        selected.micHoldTimer = null;
      });
    });
    mic.addEventListener('contextmenu', function (event) { event.preventDefault(); });
    mic.addEventListener('click', function () {
      if (held) { held = false; return; }
      var selected = rejectionSelection;
      var dot = root.PineTalkDot;
      if (!selected || !dot || typeof dot.captureNext !== 'function') {
        if (selected) { selected.message = 'Microphone unavailable'; rejectionRender(); }
        return;
      }
      if (selected.dictating) {
        dot.finish();
        selected.message = 'Transcribing...';
        el('spReviewFeedback').textContent = selected.message;
        return;
      }
      selected.dictating = true;
      mic.setAttribute('aria-pressed', 'true');
      selected.message = 'Listening...';
      el('spReviewFeedback').textContent = selected.message;
      try {
        var pending = dot.captureNext(function (words) {
          selected.dictating = false;
          if (selected !== rejectionSelection) return;
          selected.draft = rejectionAppendWords(selected.draft, words);
          var current = el('spReviewNote');
          if (current) {
            current.value = selected.draft;
            current.dispatchEvent(new Event('input', {bubbles: true}));
          }
          mic.setAttribute('aria-pressed', 'false');
          selected.message = words ? 'Dictation added' : 'No words heard';
          el('spReviewFeedback').textContent = selected.message;
          if (selected.sendAfterDictation) {
            selected.sendAfterDictation = false;
            rejectionDirectNext();
          }
        });
        if (pending && typeof pending.catch === 'function') pending.catch(function (err) {
          if (selected !== rejectionSelection) return;
          selected.dictating = false;
          selected.message = 'Microphone failed: ' + rejectionError(err);
          rejectionRender();
        });
      } catch (err) {
        selected.dictating = false;
        selected.message = 'Microphone failed: ' + rejectionError(err);
        rejectionRender();
      }
    });
    composeHead.appendChild(mic);
    editor.appendChild(composeHead);
    var input = make('textarea', 'sp-review-note');
    input.id = 'spReviewNote';
    input.rows = 3;
    input.maxLength = 2000;
    input.value = rejectionSelection.draft || '';
    input.addEventListener('input', function () {
      if (selected === rejectionSelection) selected.draft = input.value;
    });
    editor.appendChild(input);
    var actions = make('div', 'sp-review-actions');
    var save = make('button', 'sp-review-action', 'Save note');
    save.type = 'button';
    save.disabled = rejectionBusy;
    save.addEventListener('click', function () { rejectionAct('note'); });
    actions.appendChild(save);
    var direct = make('button', 'sp-review-action sp-review-direct', 'Send reply');
    direct.type = 'button';
    direct.disabled = rejectionBusy || !rejectionDirectorBody(item, record, '').kind
      || !String(rejectionSelection.draft || '').trim();
    direct.title = 'Keep this reply on the review and direct the next script of this kind';
    direct.addEventListener('click', rejectionDirectNext);
    input.addEventListener('input', function () {
      direct.disabled = rejectionBusy || !rejectionDirectorBody(item, record, '').kind
        || !String(input.value || '').trim();
    });
    actions.appendChild(direct);
    var allow = make('button', 'sp-review-action sp-review-allow', 'Allow');
    allow.type = 'button';
    allow.disabled = rejectionBusy || record.review_status !== 'pending'
      || !!record.read_only || !!record.technical;
    if (record.technical) allow.title = 'Technical failures cannot be approved as playable content';
    allow.addEventListener('click', function () { rejectionAct('allow'); });
    actions.appendChild(allow);
    var keep = make('button', 'sp-review-action sp-review-keep', 'Keep rejected');
    keep.type = 'button';
    keep.disabled = rejectionBusy || record.review_status !== 'pending' || !!record.read_only;
    keep.addEventListener('click', function () { rejectionAct('keep'); });
    actions.appendChild(keep);
    editor.appendChild(actions);
    var feedback = make('p', 'sp-review-feedback', rejectionSelection.message || '');
    feedback.setAttribute('role', 'status');
    editor.appendChild(feedback);
    scroll.appendChild(editor);
    overlay.appendChild(scroll);
    scroll.scrollTop = scrollTop;
    if (editing) input.focus();
    else if (!previousScroll) back.focus();
  }

  function rejectionFetch() {
    var selected = rejectionSelection;
    if (!selected) return Promise.resolve();
    var request = ++rejectionRequest;
    var seq = selected.item.event_seq || selected.item.seq;
    var url = '/api/orchestrator/rejections/' + encodeURIComponent(selected.item.id);
    return Promise.resolve(api().get(url)).then(function (got) {
      if (request !== rejectionRequest || selected !== rejectionSelection) return;
      if (!got || !got.id) throw new Error('Review detail unavailable');
      if (seq && Number(seq) !== Number(got.latest_seq)) {
        return Promise.resolve(api().get(url + '?event_seq=' + encodeURIComponent(seq)))
          .then(function (occurrence) {
            if (request !== rejectionRequest || selected !== rejectionSelection) return;
            if (!occurrence || !occurrence.id) throw new Error('This occurrence is no longer available');
            rejectionDetail = Object.assign({}, got, occurrence, {
              history: got.history, decisions: got.decisions,
              notes: got.notes, operator_notes: got.operator_notes,
              read_only: true, latest_seq: got.latest_seq
            });
            rejectionSelection.message = 'A newer occurrence exists. Return to live to review it.';
            rejectionRender();
          });
      }
      rejectionDetail = got;
      rejectionRender();
    }).catch(function (err) {
      if (request === rejectionRequest && selected === rejectionSelection) {
        rejectionSelection.message = rejectionError(err);
        var message = el('spReviewLoading');
        if (message) message.textContent = rejectionSelection.message;
        else if (rejectionDetail) rejectionRender();
      }
    });
  }

  function rejectionOpen(item, marker) {
    var overlay = el('spRejectionDetail');
    if (!overlay) return;
    if (rejectionSelection) rejectionClose();
    rejectionSelection = {item: item, marker: marker, draft: '', message: ''};
    rejectionDetail = null;
    overlay.hidden = false;
    overlay.parentElement.classList.add('sp-reviewing');
    overlay.replaceChildren();
    var back = make('button', 'sp-review-back', '← Live script');
    back.addEventListener('click', rejectionClose);
    overlay.appendChild(back);
    var loading = make('p', '', 'Loading review…');
    loading.id = 'spReviewLoading';
    overlay.appendChild(loading);
    back.focus();
    var selected = rejectionSelection;
    rejectionTintRead().then(function () {
      if (selected === rejectionSelection) rejectionTintPaint();
    });
    rejectionFetch();
  }

  function rejectionAct(action) {
    if (!rejectionSelection || !rejectionDetail || rejectionBusy) return;
    var selected = rejectionSelection;
    var note = String(selected.draft || '').trim();
    if (action === 'note' && !note) { selected.message = 'Enter a note first'; rejectionRender(); return; }
    if (!api().post) { selected.message = 'Station bridge unavailable'; rejectionRender(); return; }
    rejectionBusy = true;
    rejectionRender();
    var record = rejectionDetail;
    var url = '/api/orchestrator/rejections/' + encodeURIComponent(record.id);
    var body = rejectionBody(record, selected.item, action, note);
    if (action === 'note') url += '/note';
    else body.action = action;
    Promise.resolve(api().post(url, body)).then(function (got) {
      if (!got || got.ok === false) throw new Error((got && (got.detail || got.say)) || 'Station refused review');
      if (selected !== rejectionSelection) return;
      selected.draft = '';
      selected.message = action === 'note' ? 'Note saved' : 'Decision saved';
      rejectionHeadAt = 0;
      rejectionLoad(true);
      return rejectionFetch();
    }).catch(function (err) {
      if (selected !== rejectionSelection) return;
      selected.message = rejectionError(err);
      return rejectionFetch();
    }).finally(function () {
      rejectionBusy = false;
      if (selected === rejectionSelection && rejectionDetail) rejectionRender();
    });
  }

  function rejectionDirectNext() {
    if (!rejectionSelection || !rejectionDetail || rejectionBusy) return;
    var selected = rejectionSelection;
    var body = rejectionDirectorBody(selected.item, rejectionDetail, selected.draft);
    if (!body.text) { selected.message = 'Enter a direction first'; rejectionRender(); return; }
    if (!body.kind) { selected.message = 'Segment kind unavailable'; rejectionRender(); return; }
    if (!api().post) { selected.message = 'Station bridge unavailable'; rejectionRender(); return; }
    rejectionBusy = true;
    rejectionRender();
    var record = rejectionDetail;
    var url = '/api/orchestrator/rejections/' + encodeURIComponent(record.id) + '/reply';
    Promise.resolve(api().post(url, rejectionBody(record, selected.item, 'note', body.text))).then(function (got) {
      if (!got || got.ok === false) throw new Error((got && (got.detail || got.say)) || 'Direction not accepted');
      if (selected === rejectionSelection) {
        selected.draft = '';
        selected.message = 'Reply saved; next ' + body.kind + ' script directed';
        rejectionFetch();
      }
    }).catch(function (err) {
      if (selected === rejectionSelection) selected.message = 'Direction not sent: ' + rejectionError(err);
    }).finally(function () {
      rejectionBusy = false;
      if (selected === rejectionSelection && rejectionDetail) rejectionRender();
    });
  }

  /* ------------------------------------------------------------ 1, 2, 3 */

  function buildBar() {
    var bar = make('div', 'sp-bar');

    /* 1 - back to the ordinary view. */
    var back = make('button', 'sp-btn', '←');
    back.title = 'Back to the full Pine Box application';
    back.addEventListener('click', function () {
      if (root.PineViewChrome) root.PineViewChrome.show('control');
      var tech = el('pineViewTab-tech');
      if (tech) tech.click();
    });

    /* 2 - every view, as a menu. A <select> on purpose: the platform's own
     * picker is reachable with a thumb and needs no popup of my own. */
    var pick = make('select', 'sp-pick');
    var views = (root.PineViewChrome && root.PineViewChrome.VIEWS) || [];
    var head = make('option', '', 'views');
    head.value = '';
    pick.appendChild(head);
    for (var i = 0; i < views.length; i += 1) {
      var opt = make('option', '', views[i].label);
      opt.value = views[i].id;
      pick.appendChild(opt);
    }
    pick.addEventListener('change', function () {
      if (!pick.value) return;
      var tab = el('pineViewTab-' + pick.value);
      if (tab) tab.click();
      else if (root.PineViewChrome) root.PineViewChrome.show(pick.value);
      pick.value = '';
    });

    var topic = make('button', 'sp-btn sp-topics', '');
    topic.title = 'Queue a scenario for the next banter round';
    topic.setAttribute('aria-label', 'Queue a scenario for the next banter round');
    try {
      if (typeof root.pineIcon === 'function') {
        topic.innerHTML = root.pineIcon('c:add', 'Queue a scenario');
      }
    } catch (err) { /* the title still names it */ }
    if (!topic.innerHTML) topic.textContent = '+';
    topic.addEventListener('click', function () {
      var segments = root.PineSegments;
      if (segments && typeof segments.topicWindow === 'function') {
        segments.topicWindow();
      }
    });

    /* 3 - reload / re-fit. Re-reads the script and re-measures the layout,
     * which is the honest meaning of "adjust the view": anything sized by a
     * grid has no geometry until it is visible. */
    var again = make('button', 'sp-btn', '↻');
    again.title = 'Re-read the script and re-fit the view';
    again.addEventListener('click', function () {
      fetchedAt = 0;
      loadScreenplay(true);
      try { root.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
    });

    /* #1303: THE SFX GUY, ON A PICTURE, ON THE OPERATOR'S THUMB.
     *
     * Carbon out of the vendored set through pineIcon() - the house
     * rule is monochromatic Carbon and never an emoji, and the set is
     * checked before choosing. It posts the `video` road #1303 built
     * and reports what the air actually did with it: a button that
     * cues the broadcast must not be silent about whether it took. */
    var reel = make('button', 'sp-btn sp-reel', '');
    reel.title = 'Cue the SFX guy to play a random video on the broadcast';
    reel.setAttribute('aria-label', 'Play a random video clip');
    try {
      if (typeof root.pineIcon === 'function') {
        reel.innerHTML = root.pineIcon('m:video_library',
                                       'Play a random video clip');
      }
    } catch (err) { /* the title still names it */ }
    if (!reel.innerHTML) reel.textContent = 'video';
    /* #1311b: RAPID FIRE MEANS EVERY TAP COUNTS.
     *
     * This disabled the button for the length of the request, so at
     * anything faster than one tap a second the second, third and
     * fourth taps were simply swallowed - measured, five taps and the
     * picture never changed after the first. The operator asked to
     * "tap on the button, rapid fire, and have it cycle between
     * videos", so nothing is refused; a sequence number keeps a slow
     * answer from landing on top of a faster one that came after it. */
    reel.addEventListener('click', function () {
      if (reel.pineHeld) return;  /* 2026-09-14: the hold opened the folder sheet */
      reel.classList.add('sp-firing');
      fireVideo(reel);
    });
    /* 2026-09-14: HOLD IT (or right-click it) for where the clips come
     * from - the folder sheet, holdOpen() below. */
    holdOpen(reel, folderOpen);

    /* #1385 (#1108): THE PLAY BUTTON NEXT TO THE VIDEO BUTTON.
     *
     * "Put a play button next to the video button that ... puts the SFX
     *  guy into video play mode where the videos are being played one
     *  after another chosen from random from the collection."
     *
     * The mode is the station's (#1366, /api/sfx/video/mode) and it is
     * a held setting, so this button only reports and flips it; the set
     * keeps running through a restart and this view coming and going. */
    var loop = make('button', 'sp-btn sp-loop', '');
    loop.title = 'Endless video: the SFX guy plays clips one after another, at random';
    loop.setAttribute('aria-label', 'Endless video on or off');
    try {
      if (typeof root.pineIcon === 'function') {
        loop.innerHTML = root.pineIcon('c:renew', 'Endless video');
      }
    } catch (err) { /* the title still names it */ }
    if (!loop.innerHTML) loop.textContent = 'loop';
    loop.addEventListener('click', function () { loopToggle(loop); });
    setTimeout(function () { loopRead(loop); }, 900);

    /* A real deck rebuild beside the endless switch.  This keeps the
       current frame intact and replaces only the runway, so a variety pass
       cannot introduce a visible or audible gap. */
    var shuffle = make('button', 'sp-btn sp-shuffle', '');
    shuffle.title = 'Rebuild the endless-video queue from unplayed clips';
    shuffle.setAttribute('aria-label', 'Shuffle endless video queue');
    try {
      if (typeof root.pineIcon === 'function') {
        shuffle.innerHTML = root.pineIcon('m:casino', 'Shuffle endless video') || '';
      }
    } catch (err) { /* the title remains the control's name */ }
    if (!shuffle.innerHTML) shuffle.textContent = 'shuffle';
    shuffle.addEventListener('click', function () {
      var television = root.PineSfxTv;
      if (!television || typeof television.shuffle !== 'function') {
        say('the endless video deck is still connecting'); return;
      }
      shuffle.disabled = true; shuffle.classList.add('sp-firing');
      Promise.resolve(television.shuffle(say)).then(function () {
        say('endless video has a new no-repeat runway');
      }, function () { /* shuffle already printed its diagnostic */ })
        .then(function () { shuffle.disabled = false; shuffle.classList.remove('sp-firing'); });
    });

    /* #1385 (#1110): find a word that was said on the air. */
    var find = make('input', 'sp-find', '');
    find.type = 'search';
    find.placeholder = 'find a word said on air';
    find.title = 'Every time this word was said on the air in the last two days, and why it keeps being said';
    find.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); findOpen(find.value); }
    });

    /* #1115: THE SCRIPT ICON THAT FILES A REPORT.
     *
     * "place an icon here of a script that I can tap whenever the
     *  script view is not displaying the active line being said
     *  correctly. Whenever I tap the icon, place a report in the Pine
     *  inbox, along with capturing advanced diagnostic information of
     *  the script, the placement of the cursor, the activity happening
     *  with the server, and why the script display isn't displaying
     *  the active line being spoken ... capture yourself an image of a
     *  screenshot of the display of the script or the display that I'm
     *  looking at so you can see what I'm seeing."
     *
     * Everything the page knows about the highlight - the lit node and
     * whether it is even in the pane, what activeRow() and the read
     * playhead say, the scroll geometry, the errors it caught - goes to
     * /api/script/report with a picture where the chrome can take one
     * and a plain-text print of the visible script where it cannot.
     * The station adds its own reading and files the inbox report. */
    var report = make('button', 'sp-btn sp-report', '');
    report.title = 'The highlighted line is wrong? Tap: a picture of this view and everything the page knows goes to the Pine inbox';
    report.setAttribute('aria-label', 'Report the script view');
    try {
      if (typeof root.pineIcon === 'function') {
        report.innerHTML = root.pineIcon('c:script', 'Report the script view');
      }
    } catch (err) { /* the title still names it */ }
    if (!report.innerHTML) report.textContent = 'report';
    report.addEventListener('click', function () {
      if (report.pineHeld) return;  /* 2026-09-14: the hold opened the inbox */
      reportFire(report);
    });
    /* 2026-09-14: HOLD IT (or right-click it) for the Pine inbox itself -
     * what has been filed, read here, and deleted here. */
    holdOpen(report, inboxOpen);

    bar.appendChild(back);
    bar.appendChild(pick);
    bar.appendChild(topic);
    bar.appendChild(reel);                                   /* #1303 */
    bar.appendChild(sfxRepairButton());
    bar.appendChild(loop);                                   /* #1385 */
    bar.appendChild(shuffle);                                /* hourly deck */
    bar.appendChild(find);                                   /* #1385 */
    bar.appendChild(report);                                 /* #1115 */
    bar.appendChild(again);
    return bar;
  }

  /* #1298: WHAT IS BEING SAID, BESIDE THE TREE.
   *
   * The words come from activeRow() - the same answer the highlight
   * uses, so the strip and the script can never disagree. The speaker
   * is the nearest preceding character heading, which is how the
   * screenplay says it; a clip has no heading, because it is an action
   * line, so it is named as a clip instead of being given a voice it
   * does not have. */
  function buildSaying() {
    var box = make('div', 'sp-saying');
    box.id = 'spSaying';
    box.setAttribute('role', 'button');
    box.setAttribute('tabindex', '0');
    var body = make('div', 'sp-saying-body');
    var who = make('div', 'sp-saying-who', '');
    who.id = 'spSayingWho';
    var text = make('div', 'sp-saying-text', '');
    text.id = 'spSayingText';
    text.setAttribute('data-dialogue-text', '');
    /* [#1219] "Show a timeline at the bottom while the animation or the
       sound clip is playing." The label row carries the clock (0:12 / 0:22)
       and the strip rides the card's bottom edge: a fill driven by the
       sounding element - or by the tablet's native video wall, which has
       no element at all - a tick at every line boundary of a welded round
       and an amber mark at each interjection. It collapses when nothing
       sounds - see paintTimeline(). */
    var head = make('div', 'sp-saying-head');
    head.appendChild(who);
    var clk = make('i', 'sp-tl-clock', '');
    clk.id = 'spSayingClock';
    head.appendChild(clk);
    body.appendChild(head);
    body.appendChild(text);
    var scope = document.createElement('canvas');
    scope.className = 'sp-saying-scope';
    scope.id = 'spSayingScope';
    box.appendChild(body);
    box.appendChild(scope);
    var strip = make('div', 'sp-tl');
    strip.id = 'spSayingTl';
    strip.appendChild(make('i', 'sp-tl-track', ''));
    var fill = make('i', 'sp-tl-fill', '');
    fill.id = 'spSayingTlFill';
    strip.appendChild(fill);
    var marks = make('span', 'sp-tl-marks', '');
    marks.id = 'spSayingTlMarks';
    strip.appendChild(marks);
    box.appendChild(strip);
    /* PineLineActions owns the hold on data-line; a tap still follows air. */
    box.addEventListener('click', function () {
      resumeAirFollow('live strip', sayingLineId);
    });
    box.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        resumeAirFollow('live strip', sayingLineId);
      } else if ((ev.key === 'F10' && ev.shiftKey) || ev.key === 'ContextMenu') {
        var actions = root.PineLineActions;
        if (sayingLineId && actions && actions.open) {
          ev.preventDefault();
          actions.open({id: sayingLineId, said: text.textContent, node: box});
        }
      }
    });
    return box;
  }

  /* #1303b: the live line's own detail panel, off the strip.
   *
   * The node carries the current item (see paintScript), so this opens
   * what the line says NOW rather than what it said when its node was
   * first built. */
  function openSaying() {
    var id = String(sayingLineId || nowLineId || '');
    if (!id) return;
    var node = document.querySelector('.sp-el[data-line="' + id + '"]');
    if (!node || !node.pineItem) return;
    jumpToLine(id);
    openLine(node.pineItem, node);
  }

  /* Who says this line, the way the screenplay says it: the nearest
     character heading above it. */
  function sayingWho(node) {
    var walk = node;
    while (walk) {
      if (/sp-character/.test(walk.className || '')) {
        return String(walk.textContent || '').trim();
      }
      walk = walk.previousElementSibling;
    }
    return '';
  }

  var sayingSaid = '';
  var sayingLineId = '';

  function sayingSource(row, node) {
    if (node && node.pineItem) return node.pineItem;
    var id = String((row && row.id) || '');
    if (!id) return row || null;
    for (var i = 0; i < elements.length; i += 1) {
      if (String(elements[i] && (elements[i].line || elements[i].id) || '') === id) {
        return elements[i];
      }
    }
    try {
      var rows = (root.PineStationFeed && root.PineStationFeed.rows
        ? root.PineStationFeed.rows() : []) || [];
      for (var j = rows.length - 1; j >= 0; j -= 1) {
        if (String(rows[j] && (rows[j].id || rows[j].line) || '') === id) return rows[j];
      }
    } catch (err) { /* the mounted screenplay remains the first source */ }
    return row || null;
  }

  function sayingCrawl(into, words, seconds) {
    var body = String(words || '').replace(/\s+/g, ' ').trim();
    into.textContent = body;
    into.scrollTop = 0;
  }

  function paintSaying(row) {
    var who = el('spSayingWho');
    var text = el('spSayingText');
    if (!who || !text) return;
    var shown = row;
    var feedNow = null;
    try {
      feedNow = root.PineStationFeed && root.PineStationFeed.now
        ? root.PineStationFeed.now() : null;
    } catch (err) { feedNow = null; }
    var station = null;
    try { station = root.PineStationFeed && root.PineStationFeed.state
      ? root.PineStationFeed.state() : null; } catch (err) { station = null; }
    /* Feed words can enrich the player-evidenced line of the same identity.
       A clock-selected feed row never becomes the live strip's identity. */
    if (feedNow && shown && String(feedNow.id) === String(shown.id)) {
      shown = Object.assign({}, feedNow, shown, {
        text: shown.text || feedNow.text,
        name: shown.name || feedNow.name,
        who: shown.who || feedNow.who,
        kind: shown.kind || feedNow.kind
      });
    }
    /* Feedback from a control can occupy this strip only while no evidenced
       line is on air. */
    if ((!shown || !shown.id) && sayUntil && Date.now() < sayUntil) return null;
    var node = shown && shown.id ? lineNode(shown.id) : null;
    var source = sayingSource(shown, node) || {};
    var body = String((shown && shown.text) || '').trim() || (node
      ? String(node.textContent || '').trim()
      : String(source.text || source.said || source.detail || source.line_text || '').trim());
    var name = '';
    if (shown && shown.road === 'playout' && shown.speaker) {
      name = String(shown.speaker);
    } else if (node && /sp-dialogue/.test(node.className)) {
      name = sayingWho(node);
    } else if (node) {
      /* An action line IS the clip - "A sting off the board: 344 clip
         (0:35)" - so it is labelled as one rather than attributed. */
      name = 'CLIP';
    } else if (body) {
      name = String(source.name || source.who || source.speaker || source.tag || 'ON AIR');
    }
    if (!body && station && station.playing && station.now && station.now.title) {
      name = 'RECORD';
      body = String(station.now.title)
        + (station.now.artist ? ' / ' + String(station.now.artist) : '');
    } else if (!body) {
      name = station && station.paused ? 'PAUSED' : '';
      body = station && station.paused
        ? 'The station is paused while the rooms prepare the next broadcast.'
        : (soundingPlayer() ? 'Audio is playing; its line is not mapped yet.' : 'The room is quiet.');
    }
    sayingLineId = String((shown && shown.id) || '');
    var sayingBox = el('spSaying');
    if (sayingBox) {
      if (sayingLineId) {
        if (sayingBox.dataset.line !== sayingLineId) sayingBox.dataset.line = sayingLineId;
      } else if (sayingBox.dataset.line) delete sayingBox.dataset.line;
      var voice = node ? /sp-dialogue/.test(node.className || '')
        : !!(shown && !/^(sfx|music|ad|record)$/.test(String(shown.kind || ''))
          && (shown.speaker || /^(dj|host|cohost|third)$/i.test(String(shown.who || ''))));
      var spoken = String(!!voice);
      if (sayingBox.dataset.spoken !== spoken) sayingBox.dataset.spoken = spoken;
      var title = sayingLineId
        ? 'Tap to jump to this exact line in the script; hold for line actions'
        : 'What the station is playing now';
      if (sayingBox.title !== title) sayingBox.title = title;
    }
    var print = name + '\u0001' + body;
    if (print === sayingSaid) return shown;  /* no needless repaint */
    sayingSaid = print;
    who.textContent = name;
    sayingCrawl(text, body, shown && (Number(shown.until) - Number(shown.from)));
    if (sayingBox) sayingBox.classList.toggle('sp-saying-idle', !body);
    return shown;
  }

  /* THE SPECTRUM, OFF THE PANEL'S OWN ANALYSER.
   *
   * window.audioScope memoises one analyser per element and adopts
   * window.pineAudioCtx; sampler-air.js wraps that same function
   * because a second createMediaElementSource on one element throws.
   * So this never builds a context or a source - it asks for the one
   * that exists.
   *
   * On rAF rather than a timer: this tablet's WebView suspends JS
   * timers and keeps firing rAF (#1241), so rAF is the only clock here
   * that does not freeze. */
  var scopeFrame = 0;
  var scopeWide = 0;
  var scopeHigh = 0;

  /* ------------------------------------------------ [#1219] THE TIMELINE
   *
   * "Show a timeline at the bottom while the animation or the sound clip
   *  is playing."
   *
   * WHAT IT READS. The strip is driven by the thing that is actually
   * sounding, never by the station clock. In order: the panel's voice
   * element in this document, the CRT set's <video> when a clip with a
   * picture is on, the PineTab's NATIVE video wall when the endless set
   * has moved onto its own surface (#1426 - there is no <video> to read
   * there at all), and - on the desktop, where the panel is a <webview>
   * this document cannot reach - the playhead the shell posts out
   * (#1330). rAF, not a timer: the tablet's WebView suspends JS timers
   * and keeps firing rAF, and the scope already draws on that paced
   * frame, so the strip rides it.
   *
   * WHAT IT DRAWS. Elapsed and total as m:ss beside the label; a fill
   * whose width is currentTime / duration; for a welded round a tick at
   * every line boundary and an amber mark at each interjection - the
   * SFX guy's drops, and a hole between two lines wide enough to be a
   * sting slot - read off the committed cue sheet (the admission map,
   * #1336) when it names the file, else off the feed rows that carry
   * clip_from / clip_until for it (#1294), else off stream_now. Nothing
   * sounding: the strip collapses. The arithmetic is pure and exported
   * (PineScriptPage.timeline) so a test holds the real code. */
  var tlOn = false;
  var tlKey = '';
  var tlSecond = -1;
  var tlHoldUntil = 0;
  var tlLast = null;
  var TL_HOLD_MS = 600;            /* the beat between two lines is not silence */
  var TL_GAP_S = 0.35;             /* a hole this wide between lines is a sting slot */

  /* [#1219] THE NATIVE WALL'S PLAYHEAD, and why it is not simply read.
   *
   * PineVideoWall.state() answers from volatile fields the #1440
   * watchdog refreshes once a second, so position_ms can be a whole
   * second old and a strip pinned straight to it would lurch once a
   * second. Asked at 250 ms and stamped WHEN THE VALUE CHANGES, the
   * sample time is known to within that window and the fill runs on the
   * local clock between samples: it tracks, and it does not drift. A
   * kiosk build that reports position_age_ms makes the stamp exact. */
  var TL_WALL_ASK_MS = 250;
  var TL_WALL_STALE_MS = 1600;     /* older than this is not evidence */
  var tlWall = null;               /* {pos, span, file, moving, sampleAt, at} */
  var tlWallAsking = false;
  var tlWallAskedAt = 0;

  function timelineInterjects(row) {
    var kind = String((row && row.kind) || '').toLowerCase();
    var who = String((row && row.who) || '').toLowerCase();
    return kind === 'interject' || kind === 'sfxguy' || kind === 'sfx'
      || who === 'drop' || who === 'board';
  }

  /* at / total in seconds, rows with from / until (and kind / who when
     known) -> the fraction to fill, the ticks and the marks as fractions. */
  function timelineModel(at, total, rows) {
    var span = Number(total);
    if (!isFinite(span) || span <= 0) span = 0;
    var pos = Number(at);
    if (!isFinite(pos) || pos < 0) pos = 0;
    var out = {at: pos, total: span, fraction: 0, ticks: [], marks: []};
    if (!span) return out;
    out.fraction = Math.max(0, Math.min(1, pos / span));
    var list = [];
    var i;
    for (i = 0; i < (rows || []).length; i += 1) {
      var row = rows[i] || {};
      var from = Number(row.from), until = Number(row.until);
      if (!isFinite(from) || !isFinite(until) || until <= from || from >= span) continue;
      list.push({from: from, until: until, id: String(row.id || row.line_id || ''),
        interject: timelineInterjects(row)});
    }
    list.sort(function (a, b) { return a.from - b.from; });
    var seen = Object.create(null);
    var put = function (kind, t, id) {
      var f = Math.max(0, Math.min(1, t / span));
      var k = kind + ':' + f.toFixed(4);
      if (seen[k]) return;
      seen[k] = true;
      out[kind].push({at: f, id: id || ''});
    };
    for (i = 0; i < list.length; i += 1) {
      var one = list[i];
      if (one.interject) put('marks', one.from, one.id);
      else if (one.from > 0.05) put('ticks', one.from, one.id);
      var next = list[i + 1];
      if (next && next.from - one.until >= TL_GAP_S) put('marks', one.until, '');
    }
    return out;
  }

  /* The rows that describe the sounding file, and the road they came by:
     the admitted cue sheet, the feed's rows for that file, stream_now.
     The feed's windows are read through rowFrom / rowUntil because 168 of
     171 feed rows carry only clip_from / clip_until (#1294). */
  function timelineRows(file, total, admit, feed, stream) {
    var name = String(file || '');
    var span = Number(total) || 0;
    if (name && admit && admit.ok && admit.count && admit.byMedia && admit.byMedia[name]) {
      var occ = PineScriptCues.choose(admit.byMedia[name], admit.current);
      if (occ && occ.cues && occ.cues.length) {
        return {rows: occ.cues, total: span || Number(occ.seconds) || 0, road: 'admitted'};
      }
    }
    if (name && feed && feed.length) {
      var mine = [];
      for (var i = 0; i < feed.length; i += 1) {
        var row = feed[i] || {};
        if (String(row.clip_media || row.media || '') !== name) continue;
        var from = rowFrom(row), until = rowUntil(row);
        if (!isFinite(from) || !isFinite(until)) continue;
        mine.push({id: row.id, from: from, until: until, kind: row.kind, who: row.who});
      }
      if (mine.length) return {rows: mine, total: span, road: 'feed'};
    }
    if (stream && stream.rows && stream.rows.length) {
      var len = Number(stream.length) || 0;
      if (!span || !len || Math.abs(len - span) < 1.5) {
        return {rows: stream.rows, total: span || len, road: 'stream'};
      }
    }
    return {rows: [], total: span, road: 'none'};
  }

  function timelineFileOf(media) {
    var src = String((media && (media.currentSrc || media.src)) || '').split('?')[0];
    return src.split('/').pop() || '';
  }

  /* [#1219] Ask the tablet's native wall where it has got to. Paced, one
     ask in flight at a time, and never called while something nearer is
     sounding - see timelineSource(). The answer lands for a later frame;
     nothing here waits. */
  function timelineWallAsk() {
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.videoWall !== 'function') return;
    var nowMs = Date.now();
    if (tlWallAsking || nowMs - tlWallAskedAt < TL_WALL_ASK_MS) return;
    tlWallAsking = true;
    tlWallAskedAt = nowMs;
    var landed = function (got) {
      tlWallAsking = false;
      var st = got;
      if (typeof st === 'string') {
        try { st = JSON.parse(st); } catch (err) { st = null; }
      }
      var at = Date.now();
      if (!st || !st.on || st.veiled) { tlWall = null; return; }
      var pos = Number(st.position_ms);
      var span = Number(st.duration_ms);
      if (!isFinite(pos) || pos < 0 || !isFinite(span) || span <= 0) { tlWall = null; return; }
      var age = Number(st.position_age_ms);   /* a later kiosk build may say */
      var was = tlWall;
      var sampleAt;
      if (isFinite(age) && age >= 0) sampleAt = at - age;
      else if (was && was.pos === pos && was.file === String(st.playing || '')) sampleAt = was.sampleAt;
      else sampleAt = at;                     /* the value moved: sampled just now */
      tlWall = {pos: pos, span: span, file: String(st.playing || ''),
        moving: String(st.playback || '') === 'ready' && st.play_when_ready !== false,
        sampleAt: sampleAt, at: at};
    };
    try {
      var answer = bridge.videoWall('state');
      if (answer && typeof answer.then === 'function') {
        answer.then(landed, function () { tlWallAsking = false; tlWall = null; });
      } else { landed(answer); }
    } catch (err) { tlWallAsking = false; tlWall = null; }
  }

  function timelineWall() {
    timelineWallAsk();
    var got = tlWall;
    if (!got) return null;
    var nowMs = Date.now();
    if (nowMs - got.at > TL_WALL_STALE_MS) return null;
    var on = got.pos + (got.moving ? Math.max(0, nowMs - got.sampleAt) : 0);
    if (on > got.span) on = got.span;
    return {at: on / 1000, total: got.span / 1000, file: got.file, road: 'wall'};
  }

  /* What is sounding, for the strip - see the note above. */
  function timelineSource() {
    var a = soundingPlayer();
    if (a) {
      return {at: Number(a.currentTime) || 0, total: Number(a.duration) || 0,
        file: timelineFileOf(a), road: 'voice'};
    }
    var v = null;
    try { v = document.querySelector('#sfxTv video, #pineWin-sfxTv video'); }
    catch (err) { v = null; }
    if (v && !v.paused && !v.ended && Number(v.currentTime) > 0) {
      return {at: Number(v.currentTime) || 0, total: Number(v.duration) || 0,
        file: timelineFileOf(v), road: 'video'};
    }
    var wall = timelineWall();
    if (wall) return wall;
    var head = bridgeHead();
    if (head && Number(head.t) > 0) {
      return {at: Number(head.t) || 0, total: Number(head.duration) || 0,
        file: String(head.file || ''), road: 'bridge'};
    }
    return null;
  }

  function paintTimelineMarks(model) {
    var box = el('spSayingTlMarks');
    if (!box) return;
    box.replaceChildren();
    var i, one;
    for (i = 0; i < model.ticks.length; i += 1) {
      one = make('i', 'sp-tl-seg', '');
      one.style.left = (model.ticks[i].at * 100).toFixed(2) + '%';
      box.appendChild(one);
    }
    for (i = 0; i < model.marks.length; i += 1) {
      one = make('i', 'sp-tl-mark', '');
      one.style.left = (model.marks[i].at * 100).toFixed(2) + '%';
      one.title = 'an interjection';
      box.appendChild(one);
    }
  }

  function paintTimeline() {
    var fill = el('spSayingTlFill');
    if (!fill) return;
    var src = timelineSource();
    var nowMs = Date.now();
    if (src) { tlHoldUntil = nowMs + TL_HOLD_MS; tlLast = src; }
    else if (tlLast && nowMs < tlHoldUntil) { src = tlLast; }
    var on = !!src;
    if (on !== tlOn) {
      tlOn = on;
      if (host) host.classList.toggle('sp-tl-on', on);
      if (!on) {
        tlKey = ''; tlSecond = -1; tlLast = null;
        var c0 = el('spSayingClock');
        if (c0) c0.textContent = '';
        fill.style.width = '0%';
        var m0 = el('spSayingTlMarks');
        if (m0) m0.replaceChildren();
      }
    }
    if (!on) return;
    var feed = [];
    try { feed = (root.PineStationFeed && root.PineStationFeed.rows()) || []; }
    catch (err) { feed = []; }
    var got = timelineRows(src.file, src.total, admitMap, feed, liveStream);
    var model = timelineModel(src.at, got.total, got.rows);
    fill.style.width = (model.fraction * 100).toFixed(2) + '%';
    var key = src.road + '|' + got.road + '|' + src.file + '|' + model.total.toFixed(1)
      + '|' + model.ticks.length + '|' + model.marks.length;
    if (key !== tlKey) { tlKey = key; paintTimelineMarks(model); }
    var sec = Math.floor(model.at);
    if (sec !== tlSecond) {
      tlSecond = sec;
      var c1 = el('spSayingClock');
      if (c1) {
        c1.textContent = clock(sec) + (model.total ? ' / ' + clock(model.total) : '');
      }
    }
  }

  /* [#1219] What the strip is reading right now, for the CDP probe in the
     D4-timeline verification sheet and for anything that has to prove the
     fill and the sound agree. Reads, never paints. */
  function timelineRead() {
    var src = timelineSource();
    var fill = el('spSayingTlFill');
    var track = el('spSayingTl');
    var said = el('spSayingClock');
    var wide = 0, of = 0;
    try {
      of = (track && track.clientWidth) || 0;
      wide = (fill && fill.getBoundingClientRect().width) || 0;
    } catch (err) { wide = 0; of = 0; }
    return {on: tlOn, road: src ? src.road : '', file: src ? src.file : '',
      at: src ? src.at : 0, total: src ? src.total : 0,
      width: wide, of: of, fraction: of ? (wide / of) : 0,
      clock: (said && said.textContent) || ''};
  }
  /* ------------------------------------------------ [#1219] end */

  /* #1413: THE SCOPE AT A TABLET'S PACE. Profiled on the PineTab
     2026-09-14 over the WebView's devtools socket: this loop and the
     panel's drawScope were a quarter of the page's main thread, at
     60 fps, and the clientWidth/offsetParent reads here forced a layout
     of a document the feed keeps dirty - Chromium's own "(program)"
     was 43% on top. The kiosk sat at 250% CPU with the video set OFF,
     and the native audio engine shares those cores; that is the
     stutter. Every 4th frame on Android, every 2nd elsewhere, and the
     layout reads once a second. */
  /* #1413d: the panel paces requestAnimationFrame itself on the tablet
     (window.PINE_PACE > 1), so the view draws on every paced frame there
     and on every second frame elsewhere. */
  var SCOPE_EVERY = (Number(root.PINE_PACE) > 1) ? 1 : 2;
  var scopeTick = 0;
  var scopeSizeAt = 0;
  var scopeSeen = false;
  function paintScope() {
    scopeFrame = root.requestAnimationFrame(paintScope);
    scopeTick = (scopeTick + 1) % SCOPE_EVERY;
    if (scopeTick) return;
    var canvas = el('spSayingScope');
    if (!canvas) return;
    var dpr = root.devicePixelRatio || 1;
    var nowMs = Date.now();
    if (nowMs - scopeSizeAt > 1000) {
      scopeSizeAt = nowMs;
      /* #745's lesson, on our own canvas: it costs nothing while it
         cannot be seen. */
      scopeSeen = !!canvas.offsetParent;
      if (scopeSeen) {
        var wide = Math.round(canvas.clientWidth * dpr);
        var high = Math.round(canvas.clientHeight * dpr);
        /* #745 again: writing canvas.width resets the whole 2D context, so
           it is measured and compared, never assigned every frame. */
        if (wide && high && (wide !== scopeWide || high !== scopeHigh)) {
          canvas.width = wide; canvas.height = high;
          scopeWide = wide; scopeHigh = high;
        }
      }
    }
    if (!scopeSeen) return;
    try { paintTimeline(); } catch (err) { /* [#1219] the strip is decoration */ }
    var player = soundingPlayer();
    var ctx2d = null;
    try { ctx2d = canvas.getContext('2d'); } catch (err) { return; }
    if (!ctx2d) return;
    if (!scopeWide || !scopeHigh) return;
    ctx2d.clearRect(0, 0, scopeWide, scopeHigh);
    var scope = null;
    if (player && typeof root.audioScope === 'function') {
      try { scope = root.audioScope(player); } catch (err) { scope = null; }
    }
    var bins = scope && scope.bins;
    if (!scope || !bins) {
      /* A flat line is the honest picture of silence. */
      ctx2d.fillStyle = 'rgba(101, 199, 218, .22)';
      ctx2d.fillRect(0, Math.floor(scopeHigh / 2), scopeWide, Math.max(1, dpr));
      return;
    }
    try { scope.analyser.getByteFrequencyData(bins); } catch (err) { return; }
    var bars = 22;
    var step = Math.max(1, Math.floor(bins.length / bars));
    var gap = Math.max(1, Math.round(dpr));
    var span = scopeWide / bars;
    ctx2d.fillStyle = 'rgba(101, 199, 218, .85)';
    for (var b = 0; b < bars; b += 1) {
      var sum = 0;
      for (var k = 0; k < step; k += 1) sum += bins[(b * step) + k] || 0;
      var level = (sum / step) / 255;
      var tall = Math.max(dpr, level * scopeHigh);
      ctx2d.fillRect(Math.round(b * span), Math.round(scopeHigh - tall),
        Math.max(1, Math.round(span) - gap), Math.round(tall));
    }
  }

  /* #1303: cue a video, and say what came back.
   *
   * Through the bridge's own post(), the way sendNote and sendBack
   * already talk to the station - not a hand-rolled fetch that would
   * have to re-derive the base URL and the key for itself. The answer
   * lands on the strip, because a button that cues the air should
   * never be silent about whether the air took it. */
  var reelTurn = 0;

  /* ---- #1385: the endless set ----------------------------------- */
  var loopOn = false;

  function loopPaint(btn) {
    if (!btn) return;
    btn.classList.toggle('on', !!loopOn);
    btn.title = loopOn
      ? 'Endless video is ON - tap to stop after the clip on the tube'
      : 'Endless video: the SFX guy plays clips one after another, at random';
  }

  function loopRead(btn) {
    if (!api() || !api().get) return;
    Promise.resolve(api().get('/api/sfx/video/mode')).then(function (got) {
      loopOn = !!(got && got.on);
      loopPaint(btn);
    }, function () { /* asked again next time */ });
  }

  function loopToggle(btn) {
    if (!api() || !api().post) return;
    var want = !loopOn;
    loopOn = want;
    loopPaint(btn);
    Promise.resolve(api().post('/api/sfx/video/mode', {on: want})).then(function (got) {
      loopOn = !!(got && got.on !== undefined ? got.on : want);
      loopPaint(btn);
      say(loopOn ? 'endless video is on - one clip after another'
                 : 'endless video is off - back to the dial');
    }, function (err) {
      loopOn = !want;
      loopPaint(btn);
      say('the station did not answer: ' + String((err && err.message) || err).slice(0, 60));
    });
  }

  /* ---- 2026-09-14: the folder sheet ------------------------------ */

  /* WHERE THE CLIPS COME FROM, ON A HOLD OF THE VIDEO BUTTON.
   *
   * "If I tap and hold on this button, show a dialogue window that
   *  allows me to specify what folder out of all the folders in the
   *  SFX collection clips are being taken out of for the next hour. At
   *  the top of the window, offer a slider for how many hours we're
   *  sticking with the same folder ... scan all the folders and list
   *  all of the folders, allowing me to expand it with a tri and
   *  preview any of the clips inside of it just to see what the folder
   *  contains. And then I want to be able to check a folder and
   *  basically have that folder and subfolders possibly be the active
   *  folder that all clips are used from by the SFX guy for the next
   *  hour or hours. Also the same thing for videos ... endless video
   *  ... that is the same folder that they'll refer to."
   *
   * The station keeps the pin: GET /api/sfx/folders lists every folder
   * of the collection, sorted by path, each with its counts and a
   * handful of samples, plus the pin in force; POST /api/sfx/folder-pin
   * sets one (its subfolders included) for so many hours, or clears
   * it. The SFX guy - the random sting, the cue button and the endless
   * set alike - draws from the pinned folder until the pin runs out.
   * This sheet only draws what the station said and posts what the
   * operator chose; nothing about the choice lives in the page, so the
   * tablet and the desk always show the same pin.
   *
   * THE HOLD. A short tap still cues a video exactly as before - the
   * operator taps that button rapid fire and every tap must count
   * (#1311b). The sheet opens on a hold of half a second with the
   * finger still (eight pixels of travel is a scroll, not a hold), or
   * on a right-click at the desk. The click the platform fires after a
   * hold is swallowed, once, so the sheet never opens with a clip cued
   * underneath it; the next pointerdown starts a fresh gesture. The
   * same hold (holdOpen) serves the caution button and the report icon
   * below: the held flag rides the button, and the click handler of
   * each checks it first.
   *
   * THE PREVIEWS. A folder's samples are built when its caret opens
   * and torn down when it closes, and one folder is open at a time -
   * six media elements at most on a tablet whose WebView has gone deaf
   * under far less. Media is released (paused, src dropped, load()),
   * not merely detached: a detached <video> can hold its decoder. */
  var FOLDER_HOLD_MS = 500;
  var FOLDER_HOLD_PX = 8;
  var FOLDER_CAP = 300;             /* rows drawn at once; filter for the rest */
  var FOLDER_SAMPLES = 6;           /* previews per open folder */
  var folderData = null;            /* the station's last answer */
  var folderPin = null;             /* the pin in force, as last told */
  var folderSayTimer = 0;

  function holdOpen(btn, open) {
    var timer = 0, x0 = 0, y0 = 0;
    function cancel() { if (timer) clearTimeout(timer); timer = 0; }
    btn.addEventListener('pointerdown', function (ev) {
      btn.pineHeld = false;         /* a new gesture; the last hold is spent */
      if (ev.button !== undefined && ev.button !== 0) return;   /* the right button has its own road below */
      cancel();
      x0 = ev.clientX; y0 = ev.clientY;
      timer = setTimeout(function () {
        timer = 0;
        btn.pineHeld = true;
        open();
      }, FOLDER_HOLD_MS);
    });
    btn.addEventListener('pointermove', function (ev) {
      if (!timer) return;
      if (Math.abs(ev.clientX - x0) > FOLDER_HOLD_PX || Math.abs(ev.clientY - y0) > FOLDER_HOLD_PX) cancel();
    });
    btn.addEventListener('pointerup', cancel);
    btn.addEventListener('pointercancel', cancel);
    btn.addEventListener('pointerleave', cancel);
    /* The desk's right-click, and the tablet's own long-press menu,
       which the WebView raises at about the same half second: either
       way the sheet is the answer and the platform's menu is not. */
    btn.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      cancel();
      if (btn.pineHeld) return;     /* the hold got there first */
      btn.pineHeld = true;
      open();
    });
  }

  function folderClose() {
    var old = el('spFolderSheet');
    if (!old) return;
    folderMediaDrop(old);
    old.remove();
  }

  function folderMediaDrop(node) {
    var media = node.querySelectorAll('audio, video');
    for (var i = 0; i < media.length; i += 1) {
      try { media[i].pause(); media[i].removeAttribute('src'); media[i].load(); } catch (err) { /* already gone */ }
    }
  }

  /* The set's rule (#1399): served by the station - the kiosk's
     loopback door, or any http page - the path is already right; at
     the desk, in a file: page, the chrome knows the station's base and
     the loopback is the same fallback the set uses. */
  function stationUrl(u) {
    u = String(u || '');
    if (!u || /^https?:\/\//.test(u)) return u;
    var proto = '';
    try { proto = String(root.location && root.location.protocol); } catch (err) { proto = ''; }
    if (/^https?:$/.test(proto)) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (err) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }

  function folderIcon(name, label) {
    var out = '';
    try { if (typeof root.pineIcon === 'function') out = root.pineIcon(name, label); } catch (err) { out = ''; }
    return out || '';
  }

  function folderNum(n) {
    n = Number(n) || 0;
    try { return n.toLocaleString('en-US'); } catch (err) { return String(n); }
  }

  function folderLen(s) {
    s = Math.max(0, Math.round(Number(s) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  function folderLeft(pin) {
    var mins = 0;
    if (pin && typeof pin.hours_left === 'number') mins = pin.hours_left * 60;
    else if (pin && pin.until) mins = (Number(pin.until) * 1000 - (Date.now() + skewMs)) / 60000;
    mins = Math.max(0, Math.round(mins));
    if (mins < 90) return mins + ' min';
    var h = Math.floor(mins / 60), m = mins % 60;
    return h + ' h' + (m ? ' ' + m + ' min' : '');
  }

  function folderHoursLabel(n) {
    n = Number(n) || 1;
    return 'for the next ' + (n === 1 ? 'hour' : n + ' hours');
  }

  function folderRatioControls(top, bridge) {
    var defaults = {ads_share: 0, video_share: 80};
    var saved = {ads_share: 0, video_share: 80};
    var draft = {ads_share: 0, video_share: 80};
    var saving = false;
    var pendingSave = false;
    var sliders = {};
    var status = make('div', 'sp-folder-note', 'Loading mix ratios...');
    status.id = 'spSfxRatioStatus';
    status.setAttribute('role', 'status');
    status.style.cssText = 'padding:0;color:#8ea0ad;font-size:11px';

    function value(n, fallback) {
      n = Number(n);
      return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : fallback;
    }
    function paint(key, n) {
      var slider = sliders[key];
      slider.input.value = String(value(n, defaults[key]));
      slider.output.textContent = slider.input.value + '%';
    }
    function truth(answer) {
      if (!answer || answer.ok === false) throw new Error('Station did not return mix ratios');
      Object.keys(sliders).forEach(function (key) {
        saved[key] = value(answer[key], defaults[key]);
        draft[key] = saved[key];
        paint(key, saved[key]);
        sliders[key].input.disabled = false;
      });
      return answer.effective_video_share !== undefined
        && value(answer.effective_video_share, saved.video_share) !== saved.video_share
        ? 'Endless video mode currently overrides the MP4 share' : '';
    }
    function saveRatios() {
      if (saving) { pendingSave = true; return; }
      saving = true;
      var sent = {ads_share: draft.ads_share, video_share: draft.video_share};
      status.textContent = 'Saving mix ratios...';
      Promise.resolve().then(function () {
        return bridge.post('/api/sfx/ratios', sent);
      }).then(function (answer) {
        if (!answer || answer.ok === false) throw new Error('Station rejected the ratios');
        Object.keys(sliders).forEach(function (key) {
          saved[key] = value(answer[key], sent[key]);
          if (draft[key] === sent[key]) {
            draft[key] = saved[key];
            paint(key, saved[key]);
          }
        });
        saving = false;
        if (pendingSave) {
          pendingSave = false;
          saveRatios();
        } else {
          status.textContent = draft.ads_share === saved.ads_share
            && draft.video_share === saved.video_share
            ? 'Mix ratios saved' : 'Release slider to save mix ratio';
        }
      }).catch(function (err) {
        pendingSave = false;
        Promise.resolve().then(function () {
          return bridge.get('/api/sfx/ratios');
        }).then(truth).catch(function () {
          Object.keys(sliders).forEach(function (key) {
            draft[key] = saved[key];
            paint(key, saved[key]);
          });
        }).finally(function () {
          saving = false;
          status.textContent = 'Could not save mix ratios: '
            + String((err && err.message) || err);
        });
      });
    }
    [
      {key: 'ads_share', name: 'Generated ads vs general SFX', id: 'spSfxAdsShare'},
      {key: 'video_share', name: 'MP4 clips vs audio', id: 'spSfxVideoShare'}
    ].forEach(function (spec) {
      var row = make('label', 'sp-folder-ratio-row');
      row.style.cssText = 'display:flex;align-items:center;gap:10px;min-height:40px;'
        + 'flex-wrap:wrap;color:#dfe7ee';
      var name = make('span', 'sp-folder-ratio-name', spec.name);
      name.style.cssText = 'flex:0 1 190px;min-width:135px;font-size:12px';
      var input = make('input', 'sp-folder-ratio-dial');
      input.id = spec.id;
      input.type = 'range'; input.min = '0'; input.max = '100';
      input.step = '1'; input.value = String(defaults[spec.key]);
      input.disabled = true;
      input.style.cssText = 'flex:1 1 120px;min-width:80px;min-height:36px;'
        + 'margin:0;accent-color:#65c7da';
      input.setAttribute('aria-label', spec.name);
      var output = make('output', 'sp-folder-ratio-value', input.value + '%');
      output.style.cssText = 'width:42px;text-align:right;font-variant-numeric:tabular-nums';
      sliders[spec.key] = {input: input, output: output};
      input.addEventListener('input', function () {
        draft[spec.key] = value(input.value, saved[spec.key]);
        output.textContent = draft[spec.key] + '%';
        if (!saving) status.textContent = 'Release slider to save mix ratio';
      });
      input.addEventListener('change', function () {
        draft[spec.key] = value(input.value, saved[spec.key]);
        saveRatios();
      });
      row.appendChild(name);
      row.appendChild(input);
      row.appendChild(output);
      top.appendChild(row);
    });
    top.appendChild(status);
    return Promise.resolve().then(function () {
      return bridge.get('/api/sfx/ratios');
    }).then(function (answer) {
      status.textContent = truth(answer);
      return answer;
    }).catch(function (err) {
      status.textContent = 'Could not load mix ratios: ' + String((err && err.message) || err);
      return null;
    });
  }

  function folderH3Controls(top, bridge) {
    var saved = {enabled: true, gallery_share: 20};
    var draft = {enabled: true, gallery_share: 20};
    var saving = false;
    var pending = false;
    var section = make('div', 'sp-folder-h3');
    section.style.cssText = 'display:grid;gap:5px;padding:9px 0;border-top:1px solid #26343d';
    var toggleRow = make('label', 'sp-folder-h3-toggle');
    toggleRow.style.cssText = 'display:flex;align-items:center;gap:10px;min-height:34px;color:#dfe7ee';
    var toggle = make('input');
    toggle.id = 'spH3HourlyEnabled'; toggle.type = 'checkbox'; toggle.disabled = true;
    toggle.setAttribute('aria-label', 'Hourly H3 stingers');
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(make('span', null, 'Hourly H3 stingers'));
    section.appendChild(toggleRow);
    var ratioRow = make('label', 'sp-folder-ratio-row');
    ratioRow.style.cssText = 'display:flex;align-items:center;gap:10px;min-height:40px;'
      + 'flex-wrap:wrap;color:#dfe7ee';
    var name = make('span', 'sp-folder-ratio-name', 'H3 gallery images vs SFX clips');
    name.style.cssText = 'flex:0 1 190px;min-width:135px;font-size:12px';
    var slider = make('input', 'sp-folder-ratio-dial');
    slider.id = 'spH3GalleryShare'; slider.type = 'range'; slider.min = '0';
    slider.max = '100'; slider.step = '1'; slider.value = '20'; slider.disabled = true;
    slider.style.cssText = 'flex:1 1 120px;min-width:80px;min-height:36px;'
      + 'margin:0;accent-color:#65c7da';
    slider.setAttribute('aria-label', 'Share of hourly H3 sources from gallery images');
    var output = make('output', 'sp-folder-ratio-value', '20%');
    output.style.cssText = 'width:42px;text-align:right;font-variant-numeric:tabular-nums';
    ratioRow.appendChild(name); ratioRow.appendChild(slider); ratioRow.appendChild(output);
    section.appendChild(ratioRow);
    var status = make('div', 'sp-folder-note', 'Loading hourly H3 controls...');
    status.id = 'spH3HourlyStatus'; status.setAttribute('role', 'status');
    status.style.cssText = 'padding:0;color:#8ea0ad;font-size:11px';
    section.appendChild(status); top.appendChild(section);

    function share(value) {
      value = Number(value);
      return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 20;
    }
    function paint(state) {
      saved.enabled = state.enabled !== false;
      saved.gallery_share = share(state.gallery_share);
      draft.enabled = saved.enabled; draft.gallery_share = saved.gallery_share;
      toggle.checked = saved.enabled; slider.value = String(saved.gallery_share);
      output.textContent = saved.gallery_share + '%';
      toggle.disabled = false; slider.disabled = false;
    }
    function save() {
      if (saving) { pending = true; return; }
      saving = true;
      var sent = {enabled: draft.enabled, gallery_share: draft.gallery_share};
      status.textContent = 'Saving hourly H3 controls...';
      Promise.resolve(bridge.post('/api/h3/hourly', sent)).then(function (state) {
        if (!state) throw new Error('Station did not return hourly H3 controls');
        saved.enabled = state.enabled !== false;
        saved.gallery_share = share(state.gallery_share);
        if (draft.enabled === sent.enabled) toggle.checked = saved.enabled;
        if (draft.gallery_share === sent.gallery_share) {
          slider.value = String(saved.gallery_share);
          output.textContent = saved.gallery_share + '%';
        }
        saving = false;
        if (pending) { pending = false; save(); }
        else status.textContent = 'Hourly source mix saved: ' + (100 - saved.gallery_share)
          + '% SFX clips / ' + saved.gallery_share + '% gallery images';
      }).catch(function (err) {
        pending = false;
        Promise.resolve(bridge.get('/api/h3/hourly')).then(paint).catch(function () {
          toggle.checked = saved.enabled; slider.value = String(saved.gallery_share);
          output.textContent = saved.gallery_share + '%';
        }).finally(function () {
          saving = false;
          status.textContent = 'Could not save hourly H3 controls: '
            + String((err && err.message) || err);
        });
      });
    }
    toggle.addEventListener('change', function () { draft.enabled = !!toggle.checked; save(); });
    slider.addEventListener('input', function () {
      draft.gallery_share = share(slider.value); output.textContent = draft.gallery_share + '%';
      if (!saving) status.textContent = 'Release slider to save H3 source mix';
    });
    slider.addEventListener('change', function () { draft.gallery_share = share(slider.value); save(); });
    return Promise.resolve(bridge.get('/api/h3/hourly')).then(function (state) {
      paint(state || {});
      status.textContent = 'Hourly source mix: ' + (100 - saved.gallery_share)
        + '% SFX clips / ' + saved.gallery_share + '% gallery images';
      return state;
    }).catch(function (err) {
      status.textContent = 'Could not load hourly H3 controls: '
        + String((err && err.message) || err);
      return null;
    });
  }

  function sfxRepairButton() {
    var button = make('button', 'sp-btn sp-sfx-repair', '');
    button.type = 'button';
    button.title = 'Repair SFX Guy';
    button.setAttribute('aria-label', 'Repair SFX Guy');
    button.innerHTML = typeof root.pineIcon === 'function' ? root.pineIcon('c:tools', 'Repair SFX Guy') : '';
    if (!button.innerHTML) button.textContent = 'Repair SFX';
    button.addEventListener('click', function () { repairSfx(button); });
    return button;
  }

  var sfxRepairBusy = false;
  async function repairSfx(button) {
    if (sfxRepairBusy) return;
    sfxRepairBusy = true;
    button.disabled = true;
    var surface = null, shown = false;
    try {
      var result = await api().post('/api/sfx/repair', {});
      var deadline = Date.now() + 125000;
      while (true) {
        say('SFX repair: ' + String(result.say || result.phase || 'checking'));
        if (result.clip && !shown) {
          shown = true;
          if (!root.PineSfxTv || !root.PineSfxTv.repair) throw new Error('The SFX player needs an app update');
          surface = await root.PineSfxTv.repair(result.clip);
        }
        if (!result.busy) break;
        if (Date.now() > deadline) throw new Error('Repair is still running; check the station connection');
        await new Promise(function (resolve) { setTimeout(resolve, 1000); });
        result = await api().get('/api/sfx/repair');
      }
      if (result.phase === 'error') throw new Error(result.say);
      if (surface && !surface.ok) throw new Error(surface.detail);
      say((surface ? surface.detail + '. ' : '') + String(result.say || 'SFX settings restored'));
    } catch (error) {
      say('SFX repair: ' + String(error.message || error));
      button.classList.add('sp-fired-bad');
    } finally {
      sfxRepairBusy = false;
      button.disabled = false;
    }
  }

  function folderOpen() {
    if (!api() || !api().get) return;
    folderClose();
    var back = make('div', 'sp-find-back sp-folder-back');
    back.id = 'spFolderSheet';
    var box = make('div', 'sp-find-box sp-folder-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, 'Where the clips come from'));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', folderClose);
    head.appendChild(x);
    box.appendChild(head);
    var sayLine = make('div', 'sp-folder-say', '');
    sayLine.id = 'spFolderSay';
    sayLine.hidden = true;
    box.appendChild(sayLine);

    /* The top: how long a pin holds, what is pinned now, a way out of
       it, and a filter for a collection with hundreds of folders. */
    var top = make('div', 'sp-folder-top');
    var hoursRow = make('label', 'sp-folder-hours-row');
    var hoursLabel = make('span', 'sp-folder-hours-label', folderHoursLabel(1));
    var hours = make('input', 'sp-folder-hours');
    hours.type = 'range'; hours.min = '1'; hours.max = '12'; hours.step = '1'; hours.value = '1';
    hours.id = 'spFolderHours';
    hours.setAttribute('aria-label', 'How many hours a pinned folder holds');
    hours.addEventListener('input', function () { hoursLabel.textContent = folderHoursLabel(hours.value); });
    hoursRow.appendChild(hoursLabel);
    hoursRow.appendChild(hours);
    top.appendChild(hoursRow);
    folderRatioControls(top, api());
    top.appendChild(sfxRepairButton());
    folderH3Controls(top, api());
    var pinRow = make('div', 'sp-folder-pin-row');
    var pinLine = make('div', 'sp-folder-pin', 'asking the station\u2026');
    pinLine.id = 'spFolderPin';
    pinRow.appendChild(pinLine);
    var clear = make('button', 'sp-folder-clear', 'Clear the pin');
    clear.type = 'button';
    clear.id = 'spFolderClear';
    clear.hidden = true;
    clear.addEventListener('click', function () { folderPost({clear: true, path: ''}); });
    pinRow.appendChild(clear);
    top.appendChild(pinRow);
    var filter = make('input', 'sp-folder-filter');
    filter.type = 'search';
    filter.id = 'spFolderFilter';
    filter.placeholder = 'filter folders by name';
    filter.setAttribute('aria-label', 'Filter folders by name');
    var filterTimer = 0;
    filter.addEventListener('input', function () {
      if (filterTimer) clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { filterTimer = 0; folderPaint(); }, 150);
    });
    top.appendChild(filter);

    /* [#1251] MATCH HIS CLIPS TO WHAT IS BEING SAID.
     *
     * "I want this to be something I can toggle off and on where
     *  basically the DJ is matching the videos that are being played to
     *  the things that are being said loosely matching them either via
     *  the noun, verb, or context."
     *
     * This sheet is already the one place that answers "where does a
     * clip come from", so the switch that changes HOW one is chosen
     * belongs beside the pin that changes WHICH FOLDER it comes from.
     * This half is the SFX guy's stings; the endless set has its own
     * switch in its own sheet (sfx-tv.js), because they are two dials
     * on two different roads and the operator asked for both.
     *
     * The station holds it, not this browser: /api/sfx/match is a held
     * setting like the folder pin above it, so the desk, the panel and
     * the tablet cannot disagree about it and a restart finds it where
     * it was left. */
    var matchRow = make('div', 'sp-folder-match-row');
    matchRow.id = 'spSfxMatchRow';
    matchRow.setAttribute('style',
      'display:flex;gap:8px;align-items:center;flex-wrap:wrap;'
      + 'padding:6px 0;border-top:1px solid #23313c');
    var matchBtn = make('button', 'sp-folder-match-btn');
    matchBtn.type = 'button';
    matchBtn.id = 'spSfxMatchBtn';
    matchBtn.setAttribute('style',
      'min-height:36px;padding:0 10px;border-radius:8px;'
      + 'border:1px solid #2c7a8c;background:#1d4d5a;color:#dfe7ee;'
      + 'font-size:12px;cursor:pointer;display:flex;align-items:center;gap:6px');
    var matchDial = make('input', 'sp-folder-match-dial');
    matchDial.type = 'range';
    matchDial.id = 'spSfxMatchDial';
    matchDial.min = '0'; matchDial.max = '100'; matchDial.step = '5';
    matchDial.value = '35';
    matchDial.style.flex = '1 1 120px';
    matchDial.setAttribute('aria-label', 'How close a match has to be');
    var matchSay = make('div', 'sp-folder-match-say', '');
    matchSay.id = 'spSfxMatchSay';
    matchSay.setAttribute('style', 'flex:1 1 100%;font-size:11px;color:#93a4b3');
    matchRow.appendChild(matchBtn);
    matchRow.appendChild(matchDial);
    matchRow.appendChild(matchSay);
    top.appendChild(matchRow);
    box.appendChild(top);

    var list = make('div', 'sp-folder-list');
    list.id = 'spFolderList';
    list.appendChild(make('div', 'sp-folder-note', 'scanning the collection\u2026'));
    box.appendChild(list);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) folderClose(); });
    document.body.appendChild(back);
    matchWire();                                          /* [#1251] */

    Promise.resolve(api().get('/api/sfx/folders')).then(function (d) {
      if (!el('spFolderSheet')) return;       /* closed before the answer */
      if (!d || d.ok === false) {
        folderData = null;
        list.textContent = '';
        list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((d && d.say) || 'no folders').slice(0, 120)));
        folderPinPaint(null);
        return;
      }
      folderData = d;
      folderPinPaint(d.pin || null);
      folderPaint();
    }, function (err) {
      if (!el('spFolderSheet')) return;
      list.textContent = '';
      list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80)));
    });
  }

  function folderPinPaint(pin) {
    folderPin = pin && pin.path ? pin : null;
    var line = el('spFolderPin'), clear = el('spFolderClear');
    if (line) {
      line.textContent = folderPin
        ? 'all clips come from ' + (folderPin.name || folderPin.path) + ' for another ' + folderLeft(folderPin)
          + (folderPin.subfolders === false ? '' : ' (subfolders too)')
        : 'every folder - no pin';
      line.classList.toggle('on', !!folderPin);
    }
    if (clear) clear.hidden = !folderPin;
    /* The check marks, without redrawing the list: an open folder
       stays open with its previews. */
    var list = el('spFolderList');
    if (!list) return;
    var rows = list.querySelectorAll('.sp-folder-row');
    for (var i = 0; i < rows.length; i += 1) folderCheckPaint(rows[i]);
  }

  function folderCheckPaint(row) {
    var path = row.pineFolderPath || '';
    var check = row.querySelector('.sp-folder-check');
    if (!check) return;
    var exact = !!(folderPin && folderPin.path === path);
    var under = !exact && !!(folderPin && folderPin.subfolders !== false && path.indexOf(folderPin.path + '/') === 0);
    var hours = el('spFolderHours');
    check.innerHTML = folderIcon(exact ? 'c:checkbox--checked' : 'c:checkbox', exact ? 'Pinned - tap to clear' : 'Pin this folder');
    if (!check.innerHTML) check.textContent = exact ? '[x]' : '[ ]';
    check.setAttribute('aria-pressed', exact ? 'true' : 'false');
    check.title = exact ? 'Pinned - tap to clear the pin'
      : under ? 'Inside the pinned folder - tap to pin this one instead'
      : 'Pin this folder ' + folderHoursLabel(hours && hours.value);
    row.classList.toggle('pinned', exact);
    row.classList.toggle('under', under);
  }

  function folderPaint() {
    var list = el('spFolderList');
    if (!list || !folderData) return;
    folderMediaDrop(list);
    list.textContent = '';
    var all = folderData.folders || [];
    var filter = el('spFolderFilter');
    var q = filter ? String(filter.value || '').trim().toLowerCase() : '';
    /* Depth is the count of "/" beyond the shallowest folder listed. */
    var base = -1, i, f, slashes;
    for (i = 0; i < all.length; i += 1) {
      slashes = String(all[i].path || '').split('/').length;
      if (base < 0 || slashes < base) base = slashes;
    }
    var shown = 0, matched = 0;
    for (i = 0; i < all.length; i += 1) {
      f = all[i] || {};
      var path = String(f.path || '');
      var name = String(f.name || path);
      if (q && name.toLowerCase().indexOf(q) < 0 && path.toLowerCase().indexOf(q) < 0) continue;
      matched += 1;
      if (shown >= FOLDER_CAP) continue;
      shown += 1;
      /* Sorted by path, so a folder with children is followed by one. */
      var hasKids = (i + 1 < all.length) && String(all[i + 1].path || '').indexOf(path + '/') === 0;
      list.appendChild(folderRow(f, path.split('/').length - base, hasKids));
    }
    if (!all.length) list.appendChild(make('div', 'sp-folder-note', 'the station listed no folders'));
    else if (!matched) list.appendChild(make('div', 'sp-folder-note', 'no folder is named like that'));
    else if (matched > shown) list.appendChild(make('div', 'sp-folder-note', 'showing ' + folderNum(shown) + ' of ' + folderNum(matched) + ' folders - filter by name for the rest'));
  }

  function folderRow(f, depth, hasKids) {
    var row = make('div', 'sp-folder-row');
    row.pineFolderPath = String(f.path || '');
    row.pineDepth = depth;
    var line = make('div', 'sp-folder-line');
    line.style.paddingLeft = (6 + depth * 18) + 'px';
    var samples = f.samples || [];
    var tri = make('button', 'sp-folder-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    tri.innerHTML = folderIcon('c:caret--right', 'Show what is inside');
    if (!tri.innerHTML) tri.textContent = '>';
    if (!samples.length) {
      tri.disabled = true;
      tri.title = 'nothing to preview';
    } else {
      tri.title = 'Preview a few clips from this folder';
      tri.addEventListener('click', function (ev) { ev.stopPropagation(); folderToggle(row, samples); });
    }
    /* The box pins the folder for the slider's hours; on the folder
       already pinned it clears the pin, so one row is the whole switch. */
    var check = make('button', 'sp-folder-check', '');
    check.type = 'button';
    check.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var hours = el('spFolderHours');
      if (folderPin && folderPin.path === row.pineFolderPath) folderPost({clear: true, path: ''});
      else folderPost({path: row.pineFolderPath, hours: Math.min(12, Math.max(1, Number(hours && hours.value) || 1))});
    });
    var ico = make('span', 'sp-folder-ico', '');
    ico.innerHTML = folderIcon(hasKids ? 'c:folders' : 'c:folder', '');
    var name = make('span', 'sp-folder-name', String(f.name || f.path || ''));
    name.title = String(f.path || '');
    if (samples.length) name.addEventListener('click', function () { folderToggle(row, samples); });
    var bits = [];
    if (f.audio) bits.push(folderNum(f.audio) + (Number(f.audio) === 1 ? ' sound' : ' sounds'));
    if (f.video) bits.push(folderNum(f.video) + (Number(f.video) === 1 ? ' video' : ' videos'));
    var n = make('span', 'sp-folder-n', bits.join(' \u00b7 ') || 'empty');
    line.appendChild(tri);
    line.appendChild(check);
    line.appendChild(ico);
    line.appendChild(name);
    line.appendChild(n);
    row.appendChild(line);
    folderCheckPaint(row);
    return row;
  }

  function folderToggle(row, samples) {
    var tri = row.querySelector('.sp-folder-tri');
    var panel = row.querySelector('.sp-folder-samples');
    if (row.classList.contains('open')) {
      if (panel) { folderMediaDrop(panel); panel.remove(); }
      row.classList.remove('open');
      if (tri) tri.setAttribute('aria-expanded', 'false');
      return;
    }
    /* One folder open at a time: however many the operator looks
       into, the page holds one folder's previews. */
    var list = el('spFolderList');
    if (list) {
      var opened = list.querySelectorAll('.sp-folder-row.open');
      for (var i = 0; i < opened.length; i += 1) folderToggle(opened[i], []);
    }
    panel = make('div', 'sp-folder-samples');
    panel.style.paddingLeft = (52 + (row.pineDepth || 0) * 18) + 'px';
    for (var j = 0; j < samples.length && j < FOLDER_SAMPLES; j += 1) panel.appendChild(folderSample(samples[j]));
    row.appendChild(panel);
    row.classList.add('open');
    if (tri) tri.setAttribute('aria-expanded', 'true');
  }

  function videoFirstFrame(video, reveal, hide) {
    var generation = 0, start = NaN, pending = false, shown = false;
    function ready() {
      return video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
    }
    function commit() {
      if (shown || !ready()) return;
      shown = true;
      reveal();
    }
    function reset() {
      generation += 1;
      start = NaN;
      pending = false;
      shown = false;
      if (hide) hide();
    }
    video.addEventListener('loadstart', reset);
    video.addEventListener('emptied', reset);
    function armFrame() {
      if (!ready()) return;
      if (!Number.isFinite(start)) start = Number(video.currentTime) || 0;
      if (typeof video.requestVideoFrameCallback !== 'function' || pending) return;
      pending = true;
      var token = generation;
      try {
        video.requestVideoFrameCallback(function () {
          if (token !== generation) return;
          pending = false;
          commit();
        });
      } catch (err) { pending = false; /* playback progress remains the fallback */ }
    }
    video.addEventListener('loadeddata', armFrame);
    video.addEventListener('playing', armFrame);
    video.addEventListener('seeked', function () {
      if (!video.seeking) commit();
    });
    video.addEventListener('timeupdate', function () {
      if (!Number.isFinite(start)) { armFrame(); return; }
      if (Number.isFinite(start) && Number(video.currentTime) > start + 0.04) commit();
    });
    return reset;
  }

  function folderSample(s) {
    s = s || {};
    var item = make('div', 'sp-folder-sample');
    var top = make('div', 'sp-folder-sample-line');
    var kind = make('span', 'sp-folder-kind', '');
    if (s.video) kind.textContent = 'video';
    else {
      kind.innerHTML = folderIcon('c:music', 'sound');
      if (!kind.innerHTML) kind.textContent = 'sound';
    }
    top.appendChild(kind);
    top.appendChild(make('span', 'sp-folder-sample-name', String(s.name || s.id || '')));
    var len = make('span', 'sp-folder-sample-len', '');
    len.innerHTML = folderIcon('c:time', '');
    len.appendChild(document.createTextNode(folderLen(s.seconds)));
    top.appendChild(len);
    item.appendChild(top);
    var media;
    if (s.video) {
      media = document.createElement('video');
      media.setAttribute('playsinline', '');
      media.muted = true;
      media.setAttribute('muted', '');
      var frame = make('div', 'sp-folder-video-frame');
      frame.style.cssText = 'position:relative;width:100%;max-width:420px;height:120px;'
        + 'margin:2px 0 0;background:#000;overflow:hidden;border-radius:6px';
      var icon = document.createElement('img');
      icon.alt = '';
      icon.src = stationUrl('/spark/asset/pinebox.png');
      icon.style.cssText = 'position:absolute;width:64px;height:64px;max-width:30%;'
        + 'max-height:70%;object-fit:contain;left:50%;top:50%;'
        + 'transform:translate(-50%,-50%)';
      frame.appendChild(icon);
      if (s.poster_url || s.poster) {
        var poster = document.createElement('img');
        poster.alt = '';
        poster.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;'
          + 'object-fit:contain';
        poster.addEventListener('load', function () { icon.hidden = true; });
        poster.addEventListener('error', function () { poster.remove(); icon.hidden = false; });
        poster.src = stationUrl(s.poster_url || s.poster);
        frame.appendChild(poster);
      }
      var play = make('button', 'sp-folder-video-play');
      play.type = 'button';
      play.title = 'Play video preview';
      play.setAttribute('aria-label', 'Play video preview');
      play.innerHTML = folderIcon('c:play--filled', 'Play video preview') || 'Play';
      play.style.cssText = 'position:absolute;right:8px;bottom:8px;width:36px;'
        + 'height:36px;display:grid;place-items:center;z-index:1;'
        + 'background:#17232b;color:#edf3f5;border:1px solid #354853;'
        + 'border-radius:4px';
      play.addEventListener('click', function () {
        media.play().catch(function () { play.title = 'Video preview could not play'; });
      });
      frame.appendChild(play);
      media.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;'
        + 'max-width:none;max-height:none;margin:0;object-fit:contain;'
        + 'visibility:hidden;background:transparent';
      videoFirstFrame(media, function () {
        media.style.visibility = 'visible';
        play.style.display = 'none';
        icon.hidden = true;
        if (poster) poster.hidden = true;
      }, function () {
        media.style.visibility = 'hidden';
        play.style.display = 'grid';
        icon.hidden = !!(poster && poster.complete && poster.naturalWidth);
        if (poster) poster.hidden = false;
      });
    } else {
      media = document.createElement('audio');
    }
    media.controls = true;
    media.preload = 'none';
    media.className = 'sp-folder-media';
    media.src = stationUrl(s.url);
    if (s.video) { frame.appendChild(media); item.appendChild(frame); }
    else item.appendChild(media);
    return item;
  }


  /* [#1251] ---- the dialogue-matching switch ------------------------ */

  var matchState = null;

  function matchWord(n) {
    n = Number(n) || 0;
    if (n <= 10) return 'any loose connection';
    if (n <= 40) return 'one uncommon word out of the line';
    if (n <= 70) return 'two words, or one rare one';
    return 'only a strong match';
  }

  /* Painted from what the station holds, never from this browser's
     guess - a switch whose state only the page believes in is the fault
     #1184 wrote a paragraph about in the endless sheet. */
  function matchPaint(st) {
    if (st) matchState = st;
    var btn = el('spSfxMatchBtn'), dial = el('spSfxMatchDial'),
        say = el('spSfxMatchSay');
    if (!btn) return;
    var s = matchState || {};
    var on = !!s.stings;
    var icon = '';
    try {
      if (typeof root.pineIcon === 'function') {
        icon = root.pineIcon(on ? 'c:magic-wand--filled' : 'c:search',
                             on ? 'Matching' : 'Not matching') || '';
      }
    } catch (err) { icon = ''; }
    btn.innerHTML = icon + '<span>' + (on ? 'MATCHING the line' : 'Match the line')
      + '</span>';
    btn.style.background = on ? '#1d5a3a' : '#1d4d5a';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.title = 'His stings are chosen to fit the words just spoken - '
      + 'loosely, by a noun, a verb or the folder\'s subject. Below the '
      + 'strength below, the ordinary random draw runs instead, so he '
      + 'never goes quiet waiting for a match.';
    if (dial) {
      dial.value = String(Number(s.strength == null ? 35 : s.strength));
      dial.disabled = false;
    }
    if (say) {
      say.textContent = 'strength ' + (dial ? dial.value : '35') + ' - '
        + matchWord(dial ? dial.value : 35) + '. '
        + String(s.say || '');
    }
  }

  function matchPost(body) {
    if (!api() || !api().post) { folderSay('no bridge to the station'); return; }
    Promise.resolve(api().post('/api/sfx/match', body)).then(function (got) {
      if (!el('spSfxMatchRow')) return;
      matchPaint(got || null);
      folderSay(String((got && got.say) || 'saved'));
    }, function (err) {
      /* The station holds this, so a refusal means it did NOT change. */
      folderSay('the station would not take it: '
        + String((err && err.message) || err).slice(0, 70));
    });
  }

  function matchWire() {
    var btn = el('spSfxMatchBtn'), dial = el('spSfxMatchDial');
    if (btn) {
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        matchPost({stings: !(matchState && matchState.stings)});
      });
    }
    if (dial) {
      dial.addEventListener('input', function () {
        var say = el('spSfxMatchSay');
        if (say) say.textContent = 'strength ' + dial.value + ' - '
          + matchWord(dial.value) + '.';
      });
      dial.addEventListener('change', function () {
        matchPost({strength: Number(dial.value)});
      });
    }
    if (!api() || !api().get) return;
    Promise.resolve(api().get('/api/sfx/match')).then(function (st) {
      if (!el('spSfxMatchRow')) return;      /* closed before the answer */
      matchPaint(st || null);
    }, function () { /* the row paints its default and says nothing */ });
    matchPaint(null);
  }

  function folderPost(body) {
    if (!api() || !api().post) { folderSay('no bridge to the station'); return; }
    folderSay('asking the station\u2026', true);
    Promise.resolve(api().post('/api/sfx/folder-pin', body)).then(function (got) {
      if (!el('spFolderSheet')) return;
      if (!got || got.ok === false) { folderSay(String((got && got.say) || 'the station refused')); return; }
      folderPinPaint(got.pin || null);
      folderSay(String(got.say || (got.pin && got.pin.path ? 'pinned ' + (got.pin.name || got.pin.path) : 'the pin is cleared')));
    }, function (err) {
      folderSay('the station did not answer: ' + String((err && err.message) || err).slice(0, 80));
    });
  }

  /* `say` from the station, under the header, for four seconds. */
  function folderSay(text, hold) {
    var line = el('spFolderSay');
    if (!line) return;
    if (folderSayTimer) clearTimeout(folderSayTimer);
    folderSayTimer = 0;
    line.textContent = String(text || '');
    line.hidden = !line.textContent;
    if (!hold) folderSayTimer = setTimeout(function () { folderSayTimer = 0; line.hidden = true; }, 4000);
  }

  /* ---- 2026-09-14: the reason sheet and the inbox sheet ------------ */

  /* One shell for every sheet this page opens over the view: the
     backdrop that closes on a tap beside the box, the box, the header
     with its title and its x, and a line under the header for what the
     station said (four seconds, unless held). The word search drew the
     first one and the folder sheet above wears the same classes; the
     two sheets below are built from this. */
  function sheetShell(id, cls, title) {
    var old = el(id);
    if (old) old.remove();
    var back = make('div', 'sp-find-back ' + cls + '-back');
    back.id = id;
    /* 2026-09-14: "if I'm interacting with one of the systems that's a
       diagnostic, then duck the broadcast audio" - the reason sheet and
       the inbox are; the SFX folder sheet is a preference and is not. */
    if (root.PineDuck && (id === 'spReasonSheet' || id === 'spInboxSheet')) {
      root.PineDuck.hold('sp-' + id, root.PineDuck.REPORT, back);
    }
    var box = make('div', 'sp-find-box ' + cls + '-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, title));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    head.appendChild(x);
    box.appendChild(head);
    var sayLine = make('div', 'sp-sheet-say', '');
    sayLine.hidden = true;
    box.appendChild(sayLine);
    back.appendChild(box);
    document.body.appendChild(back);
    function close() { var n = el(id); if (n) n.remove(); }
    x.addEventListener('click', close);
    back.addEventListener('click', function (ev) { if (ev.target === back) close(); });
    var sayTimer = 0;
    return {
      back: back, box: box, head: head, x: x, close: close,
      say: function (text, hold) {
        if (sayTimer) clearTimeout(sayTimer);
        sayTimer = 0;
        sayLine.textContent = String(text || '');
        sayLine.hidden = !sayLine.textContent;
        if (!hold && sayLine.textContent) {
          sayTimer = setTimeout(function () { sayTimer = 0; sayLine.hidden = true; }, 4000);
        }
      }
    };
  }

  /* A. WHY ARE YOU FILING THIS?  A hold (or a right-click) on the
   * caution button. A short tap still files the report on the spot,
   * as it did; the hold first asks what the operator saw, in the
   * operator's own list of complaints, with a place to write or say
   * more. The choices toggle and several may be on; the sentence they
   * make ("The lines are out of order; This is not sequential; custom:
   * ...") rides the same report road as `reason`, and the station
   * leads the inbox summary with it. Dictation borrows the dot's ear
   * (PineTalkDot.captureNext): the dot shows that it is listening, the
   * words land in the box, and a surface without a microphone says so
   * rather than pretending. */
  var REASON_CHOICES = [
    'This was unnatural',
    'Why was the script this way?',
    'This didn\'t flow correctly',
    'The lines are out of order',
    'Why did this jump like this?',
    'This is not sequential'
  ];

  function reasonClose() { var n = el('spReasonSheet'); if (n) n.remove(); }

  function reasonOpen(btn) {
    var sheet = sheetShell('spReasonSheet', 'sp-reason', 'Why are you filing this?');
    var list = make('div', 'sp-reason-list');
    function choice(text) {
      var b = make('button', 'sp-reason-choice', '');
      b.type = 'button';
      b.pineText = text;
      var mark = make('span', 'sp-reason-mark', '');
      b.appendChild(mark);
      b.appendChild(make('span', 'sp-reason-text', text));
      function paint(on) {
        mark.innerHTML = folderIcon(on ? 'c:checkbox--checked' : 'c:checkbox', '');
        if (!mark.innerHTML) mark.textContent = on ? '[x]' : '[ ]';
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.classList.toggle('on', on);
      }
      paint(false);
      b.addEventListener('click', function () { paint(b.getAttribute('aria-pressed') !== 'true'); });
      return b;
    }
    for (var i = 0; i < REASON_CHOICES.length; i += 1) list.appendChild(choice(REASON_CHOICES[i]));

    /* Custom: a row like the others, which reveals the writing box. */
    var custom = choice('Custom');
    var customBox = make('div', 'sp-reason-custom');
    customBox.hidden = true;
    var ta = make('textarea', 'sp-reason-ta', '');
    ta.placeholder = 'in your own words';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'Your own reason');
    var dictate = make('button', 'sp-reason-dictate', '');
    dictate.type = 'button';
    dictate.innerHTML = folderIcon('c:microphone', '');
    dictate.appendChild(document.createTextNode('Dictate'));
    dictate.title = 'Say it: the dot lends its ear and the words land in the box';
    dictate.addEventListener('click', function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') { sheet.say('no microphone on this surface'); return; }
      try {
        dot.captureNext(function (words) {
          words = String(words || '').trim();
          if (!words) { sheet.say('nothing was heard'); return; }
          ta.value = (ta.value ? String(ta.value).replace(/\s+$/, '') + ' ' : '') + words;
          sheet.say('heard: ' + words.slice(0, 80));
        });
        sheet.say('listening\u2026', true);
      } catch (err) {
        sheet.say('the dot could not listen: ' + String((err && err.message) || err).slice(0, 80));
      }
    });
    customBox.appendChild(ta);
    customBox.appendChild(dictate);
    custom.addEventListener('click', function () {
      customBox.hidden = custom.getAttribute('aria-pressed') !== 'true';
      if (!customBox.hidden) { try { ta.focus(); } catch (err) { /* no focus on this surface */ } }
    });
    list.appendChild(custom);
    list.appendChild(customBox);
    sheet.box.appendChild(list);

    var file = make('button', 'sp-reason-file', 'File the report');
    file.type = 'button';
    file.addEventListener('click', function () {
      var parts = [];
      var rows = list.querySelectorAll('.sp-reason-choice');
      for (var j = 0; j < rows.length; j += 1) {
        if (rows[j] === custom || rows[j].getAttribute('aria-pressed') !== 'true') continue;
        parts.push(rows[j].pineText);
      }
      var own = String(ta.value || '').replace(/\s+/g, ' ').trim();
      if (own && !customBox.hidden) parts.push('custom: ' + own);
      if (!parts.length) { sheet.say('choose a reason, or write one'); return; }
      sheet.close();
      reportKind = 'caution';
      try { reportFire(btn, parts.join('; ')); }
      finally { setTimeout(function () { reportKind = 'report'; }, 100); }
    });
    sheet.box.appendChild(file);
  }

  /* B. THE PINE INBOX, ON A HOLD OF THE REPORT ICON. The requests the
   * station holds (GET /api/pine-requests), newest first, one card
   * each: the header, the first line, and under the caret the whole
   * text - with the "### Station at the time" block folded away as
   * debug information, every data/script_reports/script_*.md the text
   * names folded under its own name and read from the station only
   * when opened (GET /api/script-reports/<name>), and a pasted picture
   * ([img:<name>]) shown from /api/pine-uploads/<name>. A card's x
   * arms first and deletes on the second tap within three seconds:
   * an inbox is not a place for a stray thumb to lose a report. The
   * delete goes through the bridge's del() where it has one, else a
   * DELETE with the station key the way talk-dot's serverKey() finds
   * it - and says so when no key is reachable. */
  function inboxClose() { var n = el('spInboxSheet'); if (n) n.remove(); }

  function inboxOpen() {
    if (!api() || !api().get) return;
    var sheet = sheetShell('spInboxSheet', 'sp-inbox', 'The Pine inbox');
    var again = make('button', 'sp-inbox-refresh', '');
    again.type = 'button';
    again.innerHTML = folderIcon('c:renew', 'Refresh');
    if (!again.innerHTML) again.textContent = 'refresh';
    again.title = 'Read the inbox again';
    again.setAttribute('aria-label', 'Refresh the inbox');
    sheet.head.insertBefore(again, sheet.x);
    var list = make('div', 'sp-inbox-list');
    sheet.box.appendChild(list);
    again.addEventListener('click', function () { inboxLoad(sheet, list); });
    inboxLoad(sheet, list);
  }

  /* Newest first: by id where the ids count, else by date. */
  function inboxOrder(r) {
    var n = Number(r && r.id);
    if (r && String(r.id).trim() !== '' && isFinite(n)) return n;
    var t = Date.parse(String((r && r.when) || ''));
    return isFinite(t) ? t / 1000 : 0;
  }

  function inboxLoad(sheet, list) {
    list.textContent = '';
    list.appendChild(make('div', 'sp-folder-note', 'reading the inbox\u2026'));
    Promise.resolve(api().get('/api/pine-requests')).then(function (d) {
      if (!el('spInboxSheet')) return;
      list.textContent = '';
      var rows = ((d && d.requests) || []).slice();
      if (!rows.length) { list.appendChild(make('div', 'sp-folder-note', 'Inbox empty')); return; }
      rows.sort(function (a, b) { return inboxOrder(b) - inboxOrder(a); });
      for (var i = 0; i < rows.length; i += 1) list.appendChild(inboxCard(sheet, list, rows[i]));
    }, function (err) {
      if (!el('spInboxSheet')) return;
      list.textContent = '';
      list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80)));
    });
  }

  function inboxFirstLine(text) {
    var lines = String(text || '').split('\n');
    for (var i = 0; i < lines.length; i += 1) {
      var t = lines[i].replace(/^#+\s*/, '').trim();
      if (t) return t.length > 140 ? t.slice(0, 139) + '\u2026' : t;
    }
    return '(empty)';
  }

  function inboxCard(sheet, list, r) {
    var card = make('div', 'sp-inbox-card');
    var id = String((r && r.id) || '');
    var text = String((r && r.text) || '');
    card.pineReports = {};                 /* name -> text, read once */
    /* #1140: the card carries its own id and text, so a kept picture can
       re-render it from the station's `edited` row (inboxRepaint). */
    card.pineId = id;
    card.pineText = text;
    var line = make('div', 'sp-inbox-line');
    var tri = make('button', 'sp-folder-tri sp-inbox-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    tri.innerHTML = folderIcon('c:caret--right', 'Open');
    if (!tri.innerHTML) tri.textContent = '>';
    var main = make('div', 'sp-inbox-main');
    var head = make('b', 'sp-inbox-head', '#' + id + ' \u00b7 ' + String((r && r.when) || ''));
    if (r && r.status) head.appendChild(make('span', 'sp-inbox-status', ' \u00b7 ' + String(r.status)));
    main.appendChild(head);
    main.appendChild(make('span', 'sp-inbox-first', inboxFirstLine(text)));
    function toggle() {
      var open = card.classList.contains('open');
      var body = card.querySelector('.sp-inbox-body');
      if (open) {
        if (body) body.remove();
        card.classList.remove('open');
        tri.setAttribute('aria-expanded', 'false');
        return;
      }
      card.appendChild(inboxBody(card, card.pineText));
      card.classList.add('open');
      tri.setAttribute('aria-expanded', 'true');
    }
    tri.addEventListener('click', function (ev) { ev.stopPropagation(); toggle(); });
    main.addEventListener('click', toggle);

    var x = make('button', 'sp-inbox-x', '\u00d7');
    x.type = 'button';
    x.title = 'Delete this request (tap twice)';
    x.setAttribute('aria-label', 'Delete request ' + id);
    var armTimer = 0;
    x.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (!x.classList.contains('armed')) {
        x.classList.add('armed');
        sheet.say('tap again to delete #' + id);
        armTimer = setTimeout(function () { armTimer = 0; x.classList.remove('armed'); }, 3000);
        return;
      }
      if (armTimer) clearTimeout(armTimer);
      armTimer = 0;
      x.classList.remove('armed');
      x.disabled = true;
      inboxDelete(id).then(function (got) {
        if (got && got.ok === false) { x.disabled = false; sheet.say(String(got.say || 'the station refused')); return; }
        card.remove();
        sheet.say('#' + id + ' deleted');
        if (!list.querySelector('.sp-inbox-card')) list.appendChild(make('div', 'sp-folder-note', 'Inbox empty'));
      }, function (err) {
        x.disabled = false;
        sheet.say('not deleted: ' + String((err && err.message) || err).slice(0, 80));
      });
    });
    line.appendChild(tri);
    line.appendChild(main);
    line.appendChild(x);
    card.appendChild(line);
    return card;
  }

  /* The "### Station at the time" block, from that heading to the next
     heading of its level or shallower (deeper ones are its own). */
  function inboxSplit(text) {
    var at = text.indexOf('### Station at the time');
    if (at < 0) return {main: text, debug: ''};
    var rest = text.slice(at);
    var next = rest.search(/\n#{1,3} /);
    if (next < 0) return {main: text.slice(0, at), debug: rest};
    return {main: text.slice(0, at) + rest.slice(next + 1), debug: rest.slice(0, next)};
  }

  function inboxReportNames(text) {
    var re = /data\/script_reports\/(script_[\w.-]+\.md)/g, m, seen = {}, out = [];
    while ((m = re.exec(text))) {
      if (!seen[m[1]]) { seen[m[1]] = true; out.push(m[1]); }
    }
    return out;
  }

  /* Text as <pre> that wraps; a [img:<name>] token becomes the picture.
   *
   * #1140: "When following reports allow me to tap the image to full
   * screen it and basically use my finger as a cursor to draw on it in
   * red and then go back." A tap on the picture opens the hot corners'
   * red-ink annotator (PineHotCorners.annotate) full screen on THAT
   * picture, with Undo / Clear / Back / Keep. Back changes nothing; Keep
   * PUTs the drawn-on copy to the station (inboxKeep), which saves it as
   * a new upload, rewrites the card's [img:] token to it, and answers the
   * edited row - the card is repainted from that. */
  function inboxRender(into, text, card) {
    var re = /\[img:([^\]\s]+)\]/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) into.appendChild(make('pre', 'sp-inbox-pre', text.slice(last, m.index)));
      var img = document.createElement('img');
      img.className = 'sp-inbox-img';
      img.alt = m[1];
      img.loading = 'lazy';
      img.src = stationUrl('/api/pine-uploads/' + encodeURIComponent(m[1]));
      if (card) inboxInk(img, m[1], card);
      into.appendChild(img);
      last = m.index + m[0].length;
    }
    if (last < text.length) into.appendChild(make('pre', 'sp-inbox-pre', text.slice(last)));
  }

  function inboxInk(img, name, card) {
    img.title = 'Tap to draw on this picture';
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var hc = root.PineHotCorners;
      if (!hc || typeof hc.annotate !== 'function') {
        inboxSay('the annotator is not loaded on this surface');
        return;
      }
      hc.annotate('/api/pine-uploads/' + encodeURIComponent(name), {
        fileLabel: 'Keep', fileIcon: 'c:save', busyLabel: 'keeping…',
        backLabel: 'Back', cancelSay: 'nothing changed',
        note: 'draw on the picture in red, then Keep it - or go Back',
        onDone: function (png) {
          return inboxKeep(card.pineId, png, name).then(function (got) {
            if (!got || got.ok === false) throw new Error(String((got && (got.say || got.detail)) || 'the station refused'));
            inboxRepaint(card, got, img);
            inboxSay('picture kept');
          });
        }
      });
    });
  }

  /* The inbox sheet's own say-line (sheetShell's .sp-sheet-say), for a
     word after the annotator has closed. Nothing if the sheet is gone. */
  function inboxSay(words) {
    var sheet = el('spInboxSheet');
    var say = sheet && sheet.querySelector('.sp-sheet-say');
    if (!say) return;
    words = String(words || '');
    say.textContent = words;
    say.hidden = !words;
    if (words) setTimeout(function () { if (say.textContent === words) say.hidden = true; }, 4000);
  }

  /* After Keep: the <img> in the card goes to the new upload and the
     card's text is re-rendered from the station's `edited` row - the
     [img:] token now names the drawn-on copy. */
  function inboxRepaint(card, got, img) {
    var edited = (got && got.edited) || {};
    var url = String((got && got.url) || '');
    if (url && img) img.src = stationUrl(url) + (url.indexOf('?') < 0 ? '?v=' + Date.now() : '');
    if (edited && typeof edited.text === 'string') {
      card.pineText = String(edited.text);
      var first = card.querySelector('.sp-inbox-first');
      if (first) first.textContent = inboxFirstLine(card.pineText);
      var body = card.querySelector('.sp-inbox-body');
      if (body) {
        body.remove();
        card.appendChild(inboxBody(card, card.pineText));
      }
    }
  }

  function inboxBody(card, text) {
    var body = make('div', 'sp-inbox-body');
    var cut = inboxSplit(text);
    inboxRender(body, cut.main, card);
    if (cut.debug) {
      var dbg = make('details', 'sp-inbox-details');
      dbg.appendChild(make('summary', null, 'debug information'));
      dbg.appendChild(make('pre', 'sp-inbox-pre', cut.debug));
      body.appendChild(dbg);
    }
    var names = inboxReportNames(text);
    for (var i = 0; i < names.length; i += 1) body.appendChild(inboxReport(card, names[i]));
    return body;
  }

  function inboxReport(card, name) {
    var d = make('details', 'sp-inbox-details sp-inbox-report');
    d.appendChild(make('summary', null, name));
    var pre = make('pre', 'sp-inbox-pre', '');
    d.appendChild(pre);
    d.addEventListener('toggle', function () {
      if (!d.open) return;
      if (card.pineReports[name] !== undefined) { pre.textContent = card.pineReports[name]; return; }
      if (d.pineAsking) return;
      d.pineAsking = true;
      pre.textContent = 'reading\u2026';
      Promise.resolve(api().get('/api/script-reports/' + encodeURIComponent(name))).then(function (got) {
        d.pineAsking = false;
        var t = String((got && got.text) || (got && got.say) || '(empty)');
        if (!got || got.status !== 'awaiting_post') card.pineReports[name] = t;
        pre.textContent = t;
      }, function (err) {
        d.pineAsking = false;             /* asked again on the next open */
        pre.textContent = 'not read: ' + String((err && err.message) || err).slice(0, 80);
      });
    });
    return d;
  }

  /* The station key the way talk-dot's serverKey() finds it: the page's
     SERVER_KEY, else the bridge's config. */
  function inboxKey() {
    try { if (typeof root.SERVER_KEY === 'string' && root.SERVER_KEY) return Promise.resolve(root.SERVER_KEY); }
    catch (err) { /* no such global */ }
    var bridge = api();
    if (!bridge || typeof bridge.readConfig !== 'function') return Promise.resolve('');
    return Promise.resolve(bridge.readConfig()).then(function (cfg) {
      return String((cfg && (cfg.apiKey || cfg.api_key)) || '');
    }, function () { return ''; });
  }

  function inboxDelete(id) {
    var path = '/api/pine-requests/' + encodeURIComponent(id);
    var bridge = api();
    if (bridge && typeof bridge.del === 'function') return Promise.resolve(bridge.del(path));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to delete through'));
    return inboxKey().then(function (key) {
      if (!key) throw new Error('no station key reachable on this surface');
      return root.fetch(stationUrl(path), {method: 'DELETE', headers: {Authorization: 'Bearer ' + key}}).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json().then(null, function () { return {ok: true}; });
      });
    });
  }

  /* #1140: the drawn-on copy goes back to the station. PUT
     /api/pine-requests/<id> with {image: <png data url>, replace: <the
     tapped picture's file name>}; the station saves the image as a new
     upload, rewrites the [img:] token, and answers {ok, edited, image,
     url}. Through the bridge's put() where it has one (the Electron
     preload and the kiosk both do), else a PUT with the station key the
     way inboxDelete does. */
  function inboxKeep(id, png, replaceName) {
    var path = '/api/pine-requests/' + encodeURIComponent(id);
    var body = {image: String(png || ''), replace: String(replaceName || '')};
    var bridge = api();
    if (bridge && typeof bridge.put === 'function') return Promise.resolve(bridge.put(path, body));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to keep it through'));
    return inboxKey().then(function (key) {
      if (!key) throw new Error('no station key reachable on this surface');
      return root.fetch(stationUrl(path), {
        method: 'PUT',
        headers: {Authorization: 'Bearer ' + key, 'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      }).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
    });
  }

  /* ---- #1164: the drop-down under the script's name --------------- */

  /* C. HOLD THE NAME OF THE SCRIPT AND SAY WHAT IS WRONG WITH IT.
   *
   * Inbox #1164, in the operator's own words:
   *
   *   "I want to be able to tap and hold on the name of the script as
   *    being run for that particular session and I want a drop-down menu
   *    that comes down that lets me pick options like complain, mark
   *    issue and report missing segment. I am noticing some of the
   *    scripts missing entire segments, for example the manager is
   *    supposed to call during the manager's segment."
   *
   * THE GESTURE IS THE ONE THIS FILE ALREADY HAS. holdOpen() above -
   * half a second, eight pixels of travel cancels it, the trailing
   * synthetic click is swallowed by `pineHeld`, and the desk's
   * right-click and the WebView's own long-press menu are both turned
   * into the same answer. The SFX button, the caution button and the
   * report icon are already on it; the heading is the fourth, and it
   * cannot fight the other three because none of them is inside it -
   * the caution button lives in #spScript and the report icon in the
   * bar on the other half of the screen.
   *
   * IT COMES DOWN, it does not arrive. sheetShell() builds a modal with
   * a backdrop in the middle of the glass, which is right for the reason
   * sheet and the inbox and wrong here: the operator asked for "a
   * drop-down menu that comes down", so this hangs off the heading
   * inside .sp-right (already position: relative) and is placed from the
   * heading's own offsets. Its `say` line copies sheetShell's four-second
   * rule so a message on this surface behaves like a message on that one.
   *
   * WHAT IT FILES, AND WHERE THAT LANDS. Every choice goes down the
   * caution button's road and no other: reportGather() for the window,
   * the motion ring and the view snapshot, then POST /api/script/report
   * through reportFire(), then the ten-second post-capture and the
   * picture. Nothing new is invented and nothing is asked of the station
   * that it does not already answer.
   *
   * AND THE CONTEXT IS WRITTEN INTO `reason`, DELIBERATELY. It would
   * read better as its own field on the view - it is structured, and a
   * field is easier to query than a sentence. It would also be thrown
   * away: normalize_view() in script_diagnostics.py says so in its own
   * docstring - "Unknown fields are excluded by schema" - and the report
   * store encodes only what that function returns, so a new key stamped
   * on the view or on its snapshot never reaches the .json or the .md.
   * `reason` is the one thing that survives whole: app.py leads the
   * inbox item with it ("Script diagnostic capture: " + reason) and
   * render_report() prints it under "## Operator report". A field that
   * is silently discarded looks, from in here, exactly like one that
   * arrived - so the hour, the script's name, the two scene headings and
   * the visible block.ord range are written where they will be read.
   * 1200 characters is the store's cap on it; the sentence below runs to
   * about three hundred.
   */
  var HEADER_MENU_ID = 'spHeadMenu';
  var HEADER_TEXT_CAP = 160;        /* a scene heading, not a scene */
  var headerUnwatch = null;         /* PineDismiss's handle on the open menu */

  /* The three the operator named, and Cancel. `ask` is the one that
     stops to let him say WHAT is missing before anything is filed -
     "the manager is supposed to call during the manager's segment" is a
     fact no diagnostic on this page could work out for itself.
     Icons are Carbon out of the vendored set through folderIcon(), and
     all four are in pine-icons.js: that is the house rule, and the set
     is checked before choosing rather than after. */
  var HEADER_CHOICES = [
    {kind: 'complain', label: 'Complain', icon: 'c:bullhorn',
     why: 'Something about this hour is wrong and you want it on the record'},
    {kind: 'mark issue', label: 'Mark issue', icon: 'c:warning--alt',
     why: 'Mark this moment: keep the ledger around it for the station to read'},
    {kind: 'report missing segment', label: 'Report missing segment', icon: 'c:misuse',
     why: 'A whole segment never happened - say which one', ask: true}
  ];

  function headerClose() {
    var menu = el(HEADER_MENU_ID);
    if (menu) menu.remove();
    if (headerUnwatch) {
      try { headerUnwatch(); } catch (err) { /* already gone */ }
      headerUnwatch = null;
    }
    var name = el('spScriptName');
    if (name) name.setAttribute('aria-expanded', 'false');
  }

  /* One heading, on one line. */
  function headerText(node) {
    return String((node && node.dataset && node.dataset.heading)
      || (node && node.pineItem && node.pineItem.text)
      || (node && node.textContent) || '')
      .replace(/\s+/g, ' ').trim().slice(0, HEADER_TEXT_CAP);
  }

  /* Where the SCRIPT put this element, as the node already carries it -
     #1330 writes data-block and data-ord onto every one. Absent on a
     plan row or a spacer, and absent is said as absent. */
  function headerOrd(node) {
    if (!node || !node.getAttribute) return '';
    var block = node.getAttribute('data-block');
    var ord = node.getAttribute('data-ord');
    if (!block && !ord) return '';
    return String(block || '?') + '.' + String(ord || '?');
  }

  function headerSeat(node) {
    try { return node.getBoundingClientRect(); }
    catch (err) { return {top: 0, bottom: 0, height: 0}; }
  }

  /* WHICH SEGMENT THE VIEW IS SHOWING, by the segment's own words.
   *
   * Two answers, because they are two different questions and on this
   * page they disagree all the time: the reader scrolls away from the
   * air (follow stands down, #1282) and then the top of the pane and the
   * lit line are in different segments. A report that named only one of
   * them would be answering the wrong one half the time.
   *
   *   top_scene   the scene heading the READER is under - the last one
   *               walked past before the first element the pane is
   *               actually showing, so a heading scrolled off the top
   *               still names the segment on screen
   *   mark_scene  the scene heading above the line that is SOUNDING
   *               (.sp-now), or nothing when nothing is lit
   *
   * DOM order is script order here - the reconciler (#1273) stitches the
   * canonical list flat - so one walk down the pane answers both, and
   * the first and last visible block.ord are the range without sorting
   * anything.
   */
  function headerWhere() {
    var out = {title: '', hour: hourKey, before: beforeKey, top_scene: '',
      mark_scene: '', block_from: '', block_to: '', visible: 0};
    var line = el('spScriptHead');
    if (line) out.title = headerText(line);
    var pane = el('spScript');
    if (!pane || !pane.querySelectorAll) return out;
    var lip = headerSeat(pane);
    var all = pane.querySelectorAll('.sp-el');
    var scene = '';
    for (var i = 0; i < all.length; i += 1) {
      var node = all[i];
      var cls = String(node.className || '');
      if (/(^|\s)sp-scene(\s|$)/.test(cls)) scene = headerText(node);
      var seat = headerSeat(node);
      var shown = seat.height > 0 && seat.bottom > lip.top && seat.top < lip.bottom;
      if (/(^|\s)sp-now(\s|$)/.test(cls)) out.mark_scene = scene;
      if (!shown) continue;
      if (!out.top_scene) out.top_scene = scene || '(no scene heading above it)';
      out.visible += 1;
      var at = headerOrd(node);
      if (at) {
        if (!out.block_from) out.block_from = at;
        out.block_to = at;
      }
    }
    return out;
  }

  /* The sentence the inbox leads with. The operator's chosen kind comes
     FIRST and alone, so "Script diagnostic capture: complain" reads as
     what it is before anything else is said; his own words about what is
     missing come second; the evidence follows, semicolon-separated the
     way the reason sheet already writes its list. */
  function headerReason(kind, note) {
    var where = headerWhere();
    var parts = [String(kind || 'complain')];
    if (note) parts.push('missing: ' + String(note).slice(0, 400));
    if (where.title) parts.push('the script: ' + where.title);
    if (where.hour) {
      parts.push('hour: ' + where.hour
        + (where.before ? ' (with ' + where.before + ' before it on the page)' : ''));
    }
    parts.push('at the top of the pane: ' + (where.top_scene || 'nothing on screen'));
    parts.push('at the mark: ' + (where.mark_scene || 'nothing is lit'));
    parts.push('visible: ' + (where.block_from
      ? 'block.ord ' + where.block_from + ' to ' + where.block_to
        + ', ' + where.visible + ' elements'
      : where.visible + ' elements, none carrying a block.ord'));
    return parts.join('; ');
  }

  function headerOpen(name) {
    var into = name && name.parentNode;
    if (!into) return null;
    headerClose();

    var menu = make('div', 'sp-headmenu');
    menu.id = HEADER_MENU_ID;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'File a report about this script');

    /* sheetShell's say line: same four seconds, same hold. */
    var sayLine = make('div', 'sp-headmenu-say', '');
    sayLine.hidden = true;
    menu.appendChild(sayLine);
    var sayTimer = 0;
    function menuSay(text, hold) {
      if (sayTimer) clearTimeout(sayTimer);
      sayTimer = 0;
      sayLine.textContent = String(text || '');
      sayLine.hidden = !sayLine.textContent;
      if (!hold && sayLine.textContent) {
        sayTimer = setTimeout(function () { sayTimer = 0; sayLine.hidden = true; }, 4000);
      }
    }

    /* The context is read BEFORE the menu goes, so the report describes
       the view the operator was looking at when he chose - not the one
       left behind once the drop-down was taken off it. */
    function fire(kind, note) {
      var reason = headerReason(kind, note);
      headerClose();
      reportFire(name, reason);
    }

    function row(cls, icon, label, why) {
      var b = make('button', 'sp-headmenu-item' + (cls ? ' ' + cls : ''), '');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      var mark = make('span', 'sp-headmenu-mark', '');
      mark.innerHTML = folderIcon(icon, '');
      if (!mark.innerHTML) mark.textContent = '\u00b7';
      b.appendChild(mark);
      b.appendChild(make('span', 'sp-headmenu-text', label));
      if (why) b.title = why;
      return b;
    }

    /* SAY WHAT IS MISSING. The reason sheet's custom row, in the same
       shape: a box that is revealed rather than always open, a Dictate
       button that borrows the dot's ear (PineTalkDot.captureNext), and
       an honest answer on a surface that has no microphone instead of a
       button that pretends. Nothing is prefilled - the words have to be
       his, because "the manager is supposed to call during the manager's
       segment" is not a thing this page could have guessed. */
    var ask = make('div', 'sp-headmenu-ask');
    ask.hidden = true;
    var ta = make('textarea', 'sp-headmenu-ta', '');
    ta.placeholder = 'what is missing from this hour?';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'What is missing from this script');
    var tools = make('div', 'sp-headmenu-row');
    var dictate = make('button', 'sp-headmenu-dictate', '');
    dictate.type = 'button';
    dictate.innerHTML = folderIcon('c:microphone', '');
    dictate.appendChild(document.createTextNode('Dictate'));
    dictate.title = 'Say it: the dot lends its ear and the words land in the box';
    dictate.addEventListener('click', function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') { menuSay('no microphone on this surface'); return; }
      try {
        dot.captureNext(function (words) {
          words = String(words || '').trim();
          if (!words) { menuSay('nothing was heard'); return; }
          ta.value = (ta.value ? String(ta.value).replace(/\s+$/, '') + ' ' : '') + words;
          menuSay('heard: ' + words.slice(0, 80));
        });
        menuSay('listening\u2026', true);
      } catch (err) {
        menuSay('the dot could not listen: ' + String((err && err.message) || err).slice(0, 80));
      }
    });
    var file = make('button', 'sp-headmenu-file', 'File the report');
    file.type = 'button';
    file.addEventListener('click', function () {
      var own = String(ta.value || '').replace(/\s+/g, ' ').trim();
      if (!own) { menuSay('say what is missing, or dictate it'); return; }
      fire('report missing segment', own);
    });
    tools.appendChild(dictate);
    tools.appendChild(file);
    ask.appendChild(ta);
    ask.appendChild(tools);

    for (var i = 0; i < HEADER_CHOICES.length; i += 1) {
      (function (choice) {
        var b = row('', choice.icon, choice.label, choice.why);
        b.addEventListener('click', function () {
          if (!choice.ask) { fire(choice.kind, ''); return; }
          var open = ask.hidden;
          ask.hidden = !open;
          b.setAttribute('aria-expanded', open ? 'true' : 'false');
          b.classList.toggle('on', open);
          if (open) { try { ta.focus(); } catch (err) { /* no focus on this surface */ } }
        });
        menu.appendChild(b);
        if (choice.ask) menu.appendChild(ask);
      })(HEADER_CHOICES[i]);
    }

    var cancel = row('sp-headmenu-cancel', 'c:close--filled', 'Cancel',
                     'Close this menu and file nothing');
    cancel.addEventListener('click', headerClose);
    menu.appendChild(cancel);

    into.appendChild(menu);
    /* Under the name, from the name's own offsets: .sp-right is the
       positioned ancestor, and the heading's height moves with the type
       setting (#1272's paper and big-type looks both change it). */
    try {
      menu.style.top = ((name.offsetTop || 0) + (name.offsetHeight || 0) + 2) + 'px';
      menu.style.left = (name.offsetLeft || 0) + 'px';
    } catch (err) { /* no geometry on this surface; the CSS stands */ }
    name.setAttribute('aria-expanded', 'true');

    /* "if I'm interacting with one of the systems that's a diagnostic,
       then duck the broadcast audio" - this menu files reports, so it is
       one. The hold is tied to the menu element, so PineDuck's sweep
       gives the radio back by itself the moment the menu leaves the
       page: no close path in here, and no route that tears this view
       down from outside, can leave the station quiet. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-' + HEADER_MENU_ID, root.PineDuck.REPORT, menu);
    }
    /* Tap away and Escape, through the one rule every other pop-up on
       this page is on. The heading is spared so its own hold re-opens
       rather than close-then-open, and `open` is answered by the menu's
       presence rather than by its measured box - a drop-down that has
       not been laid out yet is still open. */
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      headerUnwatch = root.PineDismiss.watch(menu, headerClose, [name], function () {
        return !!el(HEADER_MENU_ID);
      });
    }
    return menu;
  }

  /* ---- #1168: the menu on a segment's header ---------------------- */

  /* D. HOLD A SEGMENT'S HEADER.
   *
   * Inbox #1168, in the operator's own words:
   *
   *   "whenever i tap and hold on a segment's header, I want a right
   *    click menu offering:
   *    - inspect segment (view popup going over every aspect of how the
   *      segment was composed)
   *    - report segment (pop up report window for reporting segment,
   *      extracts script and playback records for report and allows me
   *      to dictate / type a report to file)
   *    - examine system prompt (show system prompt in pop up window
   *      allowing for edit and saving as default or new preset for
   *      segment prompt. Allow me to modify system prompts for
   *      segments)
   *
   *    Whenever I'm looking at a segment, I also want a sidebar showing
   *    a vertical infographic showing guided arrows going from path to
   *    path, from person to person representing the conversation
   *    transaction taking place and how everyone participated and
   *    coalesced in the making of the conversation going down the
   *    screen in a sidebar to the right of the pop-up."
   *
   * THE GESTURE IS ALREADY IN THIS FILE. holdOpen() - half a second,
   * eight pixels of travel cancels it, the trailing synthetic click is
   * swallowed by `pineHeld`, and the desk's right-click and the
   * WebView's own long-press are both turned into the same answer. The
   * SFX button, the caution button, the report icon and the script's
   * name (#1164) are on it; the scene heading is the fifth. The heading
   * already has a click of its own - it is the fold's handle (#1285) -
   * so that click asks `pineHeld` first, exactly the way the caution
   * button does, and a hold therefore never also folds the segment away
   * underneath its own menu.
   *
   * HOW A SEGMENT IS NAMED. By its BLOCK, which is the station's own
   * name for one conversation (#1330). The heading itself does not
   * carry one: the screenplay pushes a scene with a round and a seg id
   * and keeps `scene_block` to itself, and #1330 stamps data-block on
   * the LINES. So the block is read off the first line under the
   * heading, walked in DOM order - which the reconciler (#1273) keeps
   * as script order. A heading with no numbered line under it has no
   * block, and that is said rather than guessed.
   *
   * WHERE THE MENU GOES. Fixed, at the heading's own measured corner
   * and clamped to the glass, rather than absolute inside #spScript:
   * that pane scrolls and clips, and a drop-down that can be scrolled
   * half out of its own parent is worse than one that simply stays put
   * until it is answered. PineDismiss closes it on a tap away or
   * Escape, the one rule every pop-up on this page is on.
   */
  var SEG_MENU_ID = 'spSegMenu';
  var segMenuUnwatch = null;
  var segAsked = Object.create(null);   /* block -> {at, data}, briefly held */

  /* The seats the station has, each with a stable colour, so the same
     person is the same colour in the legend, in the arrows and in the
     line list - and on the next segment, and tomorrow. `board` and
     `drop` are not people but they take part, so they are drawn.
     Measured over 24 hours of air (2026-09-15): dj 5,038, cohost 3,707,
     board 3,166, drop 1,367, caller 695, host 89, third 3, manager 0 -
     so `host` is a real ninth seat and belongs in the table rather than
     falling through to "someone else", and `manager` is here waiting
     for its road to be switched on. */
  var SEG_SEATS = [
    {seat: 'dj', label: 'DJ', colour: '#65c7da'},
    {seat: 'cohost', label: 'Co-host', colour: '#54d18b'},
    {seat: 'host', label: 'Host', colour: '#4fb0a6'},
    {seat: 'third', label: 'Third seat', colour: '#b98cf0'},
    {seat: 'caller', label: 'Caller', colour: '#e3be63'},
    {seat: 'caller2', label: 'Second caller', colour: '#ef8f5e'},
    {seat: 'board', label: 'The board', colour: '#8fa0ad'},
    {seat: 'drop', label: 'Drop', colour: '#e06c9f'},
    {seat: 'manager', label: 'The manager', colour: '#e05c5c'}
  ];
  var SEG_SEAT_ELSE = {seat: '', label: 'someone else', colour: '#6f8291'};
  /* The tablet's frame pipeline is sensitive (2026-09-14): a segment of
     a few hundred hand-offs must not put a few hundred more nodes on
     the glass. Beyond this the sidebar says how many it did not draw. */
  var SEG_FLOW_MOST = 60;

  function segSeatLook(seat) {
    var want = String(seat || '').toLowerCase();
    for (var i = 0; i < SEG_SEATS.length; i += 1) {
      if (SEG_SEATS[i].seat === want) return SEG_SEATS[i];
    }
    return {seat: want, label: want || SEG_SEAT_ELSE.label,
      colour: SEG_SEAT_ELSE.colour};
  }

  /* "a field the station does not have is null with a sentence beside
     it, never invented" - so this page has to be able to tell nothing
     from zero, and print the difference. */
  function segHas(v) {
    return v !== undefined && v !== null && v !== '';
  }

  function segWord(v, missing) {
    return segHas(v) ? String(v) : String(missing || 'the station did not say');
  }

  /* One decimal, always - a hole of 16.7 s and one of 17 s are the same
     hole, but the station measured the first and this page must not
     print the second as though it had. The trailing .0 goes. */
  function segSecs(v) {
    if (!segHas(v) || !isFinite(Number(v))) return '';
    var n = Math.round(Number(v) * 10) / 10;
    return n + 's';
  }

  /* One fact, as a row: what it is, what the station said, and - when
     the station said nothing - the sentence it sent instead. */
  function segRow(into, key, value, why) {
    var row = make('div', 'sp-segrow');
    row.appendChild(make('span', 'sp-segrow-k', String(key)));
    var v = make('span', 'sp-segrow-v', segHas(value) ? String(value) : '—');
    if (!segHas(value)) v.classList.add('sp-segrow-none');
    row.appendChild(v);
    if (why) row.appendChild(make('span', 'sp-segrow-why', String(why)));
    into.appendChild(row);
    return row;
  }

  function segSection(into, title) {
    var box = make('div', 'sp-segsec');
    box.appendChild(make('div', 'sp-segsec-h', String(title)));
    into.appendChild(box);
    return box;
  }

  /* WHICH SEGMENT THIS HEADING IS. Everything the three pop-ups need,
     read off the DOM before anything is opened over it. */
  function segIdentity(node) {
    var out = {node: node, heading: '', seg: '', block: '', round: '',
      hour: hourKey, at: ''};
    if (!node || !node.getAttribute) return out;
    out.heading = headerText(node);
    out.seg = String(node.getAttribute('data-seg') || '');
    /* #1303b keeps the current item on the node, so the round the
       screenplay wrote this scene for is here without asking. */
    var item = node.pineItem || null;
    if (item) {
      out.round = String(item.round || '');
      if (item.hour) out.hour = String(item.hour);
      if (segHas(item.at)) out.at = String(item.at);
    }
    var walk = node.nextSibling;
    while (walk) {
      if (walk.className !== undefined
          && /(^|\s)sp-el(\s|$)/.test(String(walk.className || ''))) {
        if (/(^|\s)sp-scene(\s|$)/.test(String(walk.className || ''))) break;
        var mark = walk.getAttribute ? String(walk.getAttribute('data-seg') || '') : '';
        if (out.seg && mark && mark !== out.seg) break;
        var blk = walk.getAttribute ? String(walk.getAttribute('data-block') || '') : '';
        if (blk) { out.block = blk; break; }
      }
      walk = walk.nextSibling;
    }
    if (!out.block && item) {
      var start = scriptOrder.indexOf(node);
      for (var i = start + 1; i >= 1 && i < scriptOrder.length; i += 1) {
        var next = scriptOrder[i].pineItem || {};
        if (String(next.type || '') === 'scene') break;
        if (next.block) { out.block = String(next.block); break; }
      }
    }
    return out;
  }

  /* THE STATION'S RECORD OF ONE SEGMENT.
   *
   * GET /api/segment/inspect?block=<n> answers with the round, every
   * line in ledger order, who took part, the brief against what was
   * actually said, the timing with its holes, and the `transaction`
   * array the sidebar draws.
   *
   * Never rejects. A 404 is a real answer here - the route may still be
   * deploying, and the pop-up says so rather than failing - and so is
   * `available: false`, which is what a block older than the ledger's
   * forty-eight hours gets. Both come back in the same shape as a good
   * answer so nothing downstream has to ask which kind it got.
   *
   * AND IT IS ASKED ONCE. Inspecting a segment and then reporting it is
   * the same block twice inside a few seconds, and this file's traffic
   * rule is not decorative - 38 concurrent requests were measured
   * starving this tablet's audio for 46 seconds. A good answer is held
   * for the screenplay's own rest (twenty seconds); a refusal is never
   * held, because the route may be deploying as he reads. */
  function segInspect(block) {
    block = String(block || '');
    var held = segAsked[block];
    if (held && (Date.now() - held.at) < SCREENPLAY_REST_MS) {
      return Promise.resolve(held.data);
    }
    if (!block) {
      return Promise.resolve({available: false, block: '', why: 'No line under'
        + ' this heading carries a block number, so there is nothing for the'
        + ' station to look up. A segment is named by its block (#1330).'});
    }
    if (!api() || !api().get) {
      return Promise.resolve({available: false, block: block,
        why: 'There is no bridge to the station from this surface.'});
    }
    return Promise.resolve(api().get('/api/segment/inspect?block='
        + encodeURIComponent(block))).then(function (d) {
      if (!d || typeof d !== 'object') {
        return {available: false, block: block,
          why: 'The station answered, but with nothing in it.'};
      }
      segAsked[block] = {at: Date.now(), data: d};
      return d;
    }, function (err) {
      var msg = String((err && err.message) || err);
      var missing = /\b404\b|not\s*found/i.test(msg);
      return {available: false, block: block, unreachable: true,
        why: missing
          ? 'This station has no /api/segment/inspect yet - it may still be'
            + ' deploying. Nothing else on this menu depends on it.'
          : 'The station did not answer: ' + msg.slice(0, 140)};
    });
  }

  /* ---- #1168-1: inspect segment ----------------------------------- */

  /* "a view popup going over every aspect of how the segment was
   * composed" - the round and when it was committed, every line in
   * ledger order with its seat, voice, engine, model, length, air time
   * and aired state, who took part and for how long, the brief this
   * road was supposed to fill against what it actually contained, the
   * timing with any hole inside it, and the hand-offs.
   *
   * `heard` is the truthful one and `aired` is the raw state, so they
   * are shown as two different things: a line can be `published`
   * (handed over) and never acknowledged, or `withdrawn` (refused at
   * hand-over, with the check that refused it beside it), and a written
   * line that was never heard is common enough tonight that hiding it
   * would make this pop-up lie. */
  /* ---- #1238 / #1193 / #1194 / #1235: these surfaces answer a tap --- */

  /* WHAT THESE WINDOWS WOULD NOT DO.
   *
   *  #1238  "If I tap on either of these [the Co-host, The board and the
   *          Drop nodes of the chain], I want to see additional details
   *          about them."
   *  #1193  "I want to be able to tap elements in the sidebar and be able
   *          to see them on screen."
   *  #1194  "Allow me to tap each one in order to play its sound on the
   *          broadcast and allow me to tap and hold it to bring up the
   *          right click menu for various options pertaining to each sound
   *          effect."
   *  #1235  "[the script heading] When I tap on that I want to see the
   *          full itinerary."
   *
   * Everything in the Segment window was drawn and then left alone. The
   * chain down the right named a seat and a hand-off and gave no way to
   * reach the line it stands for; the line list printed every line of the
   * block and gave no way to HEAR one. Three gestures now, each the
   * gesture that surface already teaches elsewhere in this shell:
   *
   *   tap a chain node / an arrow   the list scrolls to that line, flashes
   *                                 it and unfolds its detail card
   *   tap a line row                the line goes back on the BROADCAST -
   *                                 POST /api/script/line/replay - not out
   *                                 of the speaker of whoever tapped
   *   hold a row 600 ms, or         the station's one hold sheet, placed
   *   right-click it                where the finger is
   *
   * THE HOLD SHEET IS NOT BUILT HERE. line-actions.js owns it and #1200
   * teaches it the sound-effect items; this file hands it the line and a
   * node carrying `pineItem` so a sting is recognised as a sting, then
   * moves it to the finger - there is no hover on a tablet and no mouse to
   * follow, and a sheet pinned to the foot of the glass is a sheet a thumb
   * on the top row has to travel the whole screen to reach.
   *
   * AND IT DRIVES THAT SHEET RATHER THAN LETTING THE DOCUMENT HANDLER DO
   * IT. line-actions.js binds one long-press on the document for anything
   * carrying `data-line`; marking these rows with that attribute would get
   * the sheet for free - and would get it TWICE, once from that handler
   * and once from the press this file has to time anyway to keep a tap
   * from being read as a hold. One timer, one sheet, one place it lands.
   *
   * THE STATION IS ASKED NOTHING EXTRA. The answer already on screen is
   * kept in `segShown` and every tap is served out of it. This file's
   * traffic rule is not decorative: 38 concurrent requests were measured
   * starving this tablet's audio for 46 seconds.
   */
  var segShown = null;            /* the open window's /api/segment/inspect */
  var segShownAt = null;          /* and the heading it was opened from */
  var segSaying = null;           /* that window's own say() line */
  var segReplaying = '';          /* a replay in flight, by line id */
  var SEG_HOLD_MS = 600;          /* the same hold line-actions.js uses */
  var SEG_HOLD_SLOP = 12;         /* a scroll is not a hold */

  /* Called from segInspectOpen, so a window opened twice never shows the
     last one's answer while the fresh one is still being asked for. */
  function segWindowOpen(sheet, ident) {
    segShown = null;
    segShownAt = ident || null;
    segSaying = (sheet && sheet.say) || null;
    segReplaying = '';
  }

  function segSay(text, hold) {
    if (typeof segSaying === 'function') {
      try { segSaying(String(text || ''), !!hold); return; } catch (err) { /* fall through */ }
    }
    caughtNote('segment', String(text || ''));
  }

  function segWhy(err) {
    var msg = String((err && (err.detail || err.message)) || err || '');
    if (/\b404\b/.test(msg)) {
      return 'This station has no replay road yet - it may still be deploying.';
    }
    return msg.slice(0, 160) || 'the station did not say why';
  }

  /* An id is only ever used inside a CSS selector after this. */
  function segTame(id) {
    return String(id || '').replace(/[^A-Za-z0-9_:.-]/g, '');
  }

  function segLineOf(lineId) {
    var lines = (segShown && segShown.lines) || [];
    var want = String(lineId || '');
    if (!want) return null;
    for (var i = 0; i < lines.length; i += 1) {
      if (String((lines[i] || {}).line_id || '') === want) return lines[i];
    }
    return null;
  }

  /* A sting is a line of the script like any other; what makes it one is
     that the station named a sample behind it (#1194 carries `sfx` and the
     signed /sfx/ road on every line of the inspect answer). `kind` alone is
     not enough - a welded sting can come through as `dialogue`. */
  function segIsSting(l) {
    if (!l) return false;
    if (String(l.kind || '') === 'sfx') return true;
    if (String(l.who || '') === 'board' || String(l.who || '') === 'drop') return true;
    return !!l.sfx;
  }

  /* ------------------------------------------------ #1193/#1238: reveal */

  function segWindowBody() {
    var win = el('spSegInspect');
    return win ? win.querySelector('.sp-segins-body') : null;
  }

  function segCardFor(lineId) {
    var win = el('spSegInspect');
    var id = segTame(lineId);
    if (!win || !id) return null;
    return win.querySelector('.sp-segline[data-line-id="' + id + '"]');
  }

  function segCardForSeat(seat) {
    var win = el('spSegInspect');
    var want = segTame(seat);
    if (!win || !want) return null;
    return win.querySelector('.sp-segline[data-seat="' + want + '"]');
  }

  /* "tap elements in the sidebar and be able to see them on screen."
   *
   * The chain is a column of seats and arrows; the answer to a tap on one
   * is the LINE it stands for, over on the left, where every fact about it
   * already is. So: scroll it into the middle of the window's own scroller,
   * flash it the way jumpToLine flashes a line of the script (the same
   * gesture, so it reads as the same answer), and unfold its card.
   *
   * A chip that is only a seat - the first node of the chain, and every
   * node of a segment that had no hand-offs at all - has no one line, so it
   * reveals that seat's FIRST line and the card says which seat it is. That
   * is honest: the station recorded the seat, not a line, for that node. */
  /* ---------------------------------------------- [#1386] TECHNICAL VIEW */
  var techView = null;          /* the mounted graph, when there is one */
  var techHost = null;          /* the div it lives in, beside the feed */
  var techOn = false;
  var techOpening = false;
  var techWide = false;         /* [#1387] across the whole bottom */
  try { techWide = localStorage.getItem('sp.tech.wide') === '1'; }
  catch (e) { techWide = false; }

  /* [#1386] ABSOLUTE, ALWAYS.
   *
   * import() resolves a RELATIVE specifier against the importing script's
   * base URL - and this file is INJECTED into the kiosk's WebView rather
   * than loaded from a URL, so its base is `about:blank` and every
   * relative path fails with "Failed to resolve module specifier". The
   * error names the cause exactly and is easy to misread as a missing
   * file, which is what it looked like.
   *
   * `pineThreeUrl` is no help either: it lives in the Electron shell's
   * renderer.js and does not exist in the panel page at all.
   *
   * So the origin is taken from the page itself when there is one - on
   * the tablet the panel is served from http://127.0.0.1:8096 - and only
   * a file:// shell falls back to naming the station outright. */
  function techUrl(name) {
    try {
      if (/^https?:$/.test(location.protocol) && location.origin
          && location.origin !== 'null') {
        return location.origin + name;
      }
    } catch (err) { /* no location worth having */ }
    try {
      if (root.pineThreeUrl) {
        return String(root.pineThreeUrl())
          .replace(/\/vendor\/three\.min\.js.*$/, '') + name;
      }
    } catch (err) { /* older shell */ }
    return 'http://127.0.0.1:8096' + name;
  }

  function techBox() {
    if (techHost) return techHost;
    var feed = document.getElementById('spFeed');
    if (!feed || !feed.parentNode) return null;
    techHost = make('div', 'sp-tech');
    techHost.style.display = 'none';
    feed.parentNode.insertBefore(techHost, feed.nextSibling);
    return techHost;
  }

  async function techMount() {
    if (techView || techOpening) return techView;
    var box = techBox();
    if (!box) return null;
    techOpening = true;
    try {
      if (!document.getElementById('spTechStyle')) {
        var style = document.createElement('link');
        style.id = 'spTechStyle';
        style.rel = 'stylesheet';
        style.href = techUrl('/word-cause/word-cause.css?v=3');
        document.head.appendChild(style);
      }
      var mod = await import(techUrl('/word-cause/word-cause.js?v=3'));
      techView = mod.openWordCause({
        embed: true,
        host: box,
        threeUrl: techUrl('/vendor/three.min.js'),
        base: location.origin,
        /* [#1387] The full-screen host is the panel's own PINE_3JS frame.
           On the tablet this code IS the panel's document, so the function
           is right there; in the desktop shell it is not, and a new window
           on the same road is the honest fallback rather than a button
           that silently does nothing. */
        onFull: function (want) {
          try {
            if (typeof root.pineShow3JS === 'function') {
              root.__wcWant = want;
              root.pineShow3JS('wordcause');
              return;
            }
          } catch (err) { /* fall through to the window */ }
          var q = '/?view=wordcause'
            + (want && want.line ? '&wc=' + encodeURIComponent(want.line) : '')
            + (want && !want.line && want.word
               ? '&wcq=' + encodeURIComponent(want.word) : '');
          try { root.open(techUrl('') + q, '_blank'); }
          catch (err) { /* a shell with no window opener */ }
        },
        request: function (path, options) { return api()[
          (options && options.method === 'PUT') ? 'put'
            : (options && options.method === 'POST') ? 'post' : 'get'](
          path, options && options.body ? JSON.parse(options.body) : undefined); },
        onClose: function () { techView = null; },
      });
    } catch (err) {
      box.textContent = '';
      box.appendChild(make('div', 'sp-techbad',
        'the technical view could not open: ' + String((err && err.message) || err)));
    } finally { techOpening = false; }
    return techView;
  }

  /* [#1387] ACROSS THE WHOLE BOTTOM.
   *
   * "I might also need to be able to expand the technical view in the
   *  script sub page to be able to go all the way across to the right side.
   *  So it's basically splitting into the script section and taking up that
   *  whole bottom section of the window, allowing me to have more room to
   *  work horizontally."
   *
   * The feed column is about a third of the glass, and a flowchart that
   * fans out five columns deep cannot be read in a third of the glass - his
   * screenshot is the proof. So the pane can leave its column: pinned to
   * the page, left to right, taking the bottom band under BOTH the column
   * and the script, with a handle on its top edge to say how much of the
   * height it gets. The script keeps running above it.
   *
   * It is the same mounted graph either way - moved, not rebuilt - so
   * nothing is re-fetched and nothing loses its place; only `resize` is
   * told, because the canvas has to be re-measured after any move. */
  function techPage() {
    var at = document.querySelector('.' + HOST_CLASS);
    return at || document.body;
  }

  function techPlace() {
    if (!techHost) return;
    var page = techPage();
    if (techWide) {
      techHost.classList.add('sp-tech-wide');
      var tall = 0;
      try { tall = parseInt(localStorage.getItem('sp.tech.tall') || '0', 10); }
      catch (e) { tall = 0; }
      techHost.style.height = (tall >= 160 ? tall : Math.round(
        (page.clientHeight || 700) * 0.55)) + 'px';
      if (techHost.parentNode !== page) page.appendChild(techHost);
    } else {
      techHost.classList.remove('sp-tech-wide');
      techHost.style.height = '';
      var feed = document.getElementById('spFeed');
      if (feed && feed.parentNode && techHost.parentNode !== feed.parentNode) {
        feed.parentNode.insertBefore(techHost, feed.nextSibling);
      }
    }
    var flip = document.querySelector('.sp-techwide');
    if (flip) {
      flip.textContent = techWide ? 'in column' : 'full width';
      flip.title = techWide
        ? 'Put the technical view back in the feed column'
        : 'Take the technical view across the whole bottom of the window';
    }
    if (techView && techView.resize) {
      setTimeout(function () { try { techView.resize(); } catch (e) { /* gone */ } }, 40);
    }
  }

  function techWideSet(on) {
    techWide = !!on;
    try { localStorage.setItem('sp.tech.wide', techWide ? '1' : '0'); }
    catch (e) { /* a private window; the choice lasts this session */ }
    /* [#1389] THE TABS GET OUT OF THE WAY.
     *
     * "whenever this is brought into full mode ... these tabs need to
     *  slide out of the way so that the buttons aren't being overlapped
     *  with by tabs because I can never tap them."
     *
     * The vertical view rail (#pineViewRail: TECH, SAMPLER, SCRIPT ...)
     * is `position: fixed; right: 0` and sits at z-index 2147483001 - so
     * it floats over ANY pane, and in full width the technical view's own
     * bar runs right underneath it. Fit, full and the layout picker were
     * all behind a tab.
     *
     * A class on <html>, exactly as listen.js's bare mode does it, because
     * rail.js injects its own stylesheet AFTER every other one: a bare
     * `#pineViewRail` rule here would lose every tie, and `html.<class>
     * #pineViewRail` is an id plus a class, which wins whatever the source
     * order. rail.js itself is untouched.
     *
     * It slides OUT, not away: a strip stays on the edge and a finger on
     * it brings the whole rail back. A control whose only way back is a
     * control you just hid is the fault in [[a-modal-needs-its-own-way-out]],
     * and this does not repeat it. */
    try {
      document.documentElement.classList.toggle('pine-tech-wide', techWide);
    } catch (e) { /* no document element is not a thing, but never throw here */ }
    techPlace();
    /* The feed only hides when the pane is IN its column. Wide, the pane is
       somewhere else entirely and the feed can carry on being the feed. */
    var feed = document.getElementById('spFeed');
    if (feed) feed.style.display = (techOn && !techWide) ? 'none' : '';
  }

  /* The handle on its top edge. Drag to say how much of the bottom band the
     drawing gets; double tap to put it back to the middle. */
  function techGrip() {
    if (!techHost || techHost.querySelector('.sp-tech-grip')) return;
    var grip = make('div', 'sp-tech-grip');
    grip.title = 'Drag to resize; double tap to put it back';
    var from = 0;
    var was = 0;
    var move = function (ev) {
      var page = techPage();
      var want = Math.max(160, Math.min(
        Math.max(240, (page.clientHeight || 700) - 140),
        was + (from - ev.clientY)));
      techHost.style.height = want + 'px';
      if (techView && techView.resize) {
        try { techView.resize(); } catch (e) { /* gone */ }
      }
    };
    var stop = function (ev) {
      try { grip.releasePointerCapture(ev.pointerId); } catch (e) { /* gone */ }
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', stop);
      grip.removeEventListener('pointercancel', stop);
      try {
        localStorage.setItem('sp.tech.tall',
          String(parseInt(techHost.style.height, 10) || 0));
      } catch (e) { /* nothing is lost but the memory */ }
    };
    grip.addEventListener('pointerdown', function (ev) {
      if (!techWide) return;
      ev.preventDefault();
      from = ev.clientY;
      was = techHost.clientHeight;
      try { grip.setPointerCapture(ev.pointerId); } catch (e) { /* older */ }
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', stop);
      grip.addEventListener('pointercancel', stop);
    });
    grip.addEventListener('dblclick', function () {
      techHost.style.height = Math.round(
        (techPage().clientHeight || 700) * 0.55) + 'px';
      try { localStorage.removeItem('sp.tech.tall'); } catch (e) { /* fine */ }
      if (techView && techView.resize) {
        try { techView.resize(); } catch (e) { /* gone */ }
      }
    });
    techHost.appendChild(grip);
  }

  function techShowFace(on) {
    var feed = document.getElementById('spFeed');
    techOn = !!on;
    /* Wide, the pane is not in the feed's place, so the feed stays. */
    if (feed) feed.style.display = (techOn && !techWide) ? 'none' : '';
    if (techHost) techHost.style.display = techOn ? '' : 'none';
    if (techOn) { techGrip(); techPlace(); }
    var flip = document.querySelector('.sp-feedflip');
    if (flip) flip.textContent = techOn ? 'feed' : 'technical';
    var name = document.querySelector('.sp-feedhead b');
    if (name) name.textContent = techOn ? 'Technical' : 'Feed';
    var why = document.querySelector('.sp-feedwhy');
    if (why) {
      why.textContent = techOn
        ? 'where it came from - pinch to zoom, tap a node, double tap to bring it in'
        : 'everything the station is doing';
    }
    if (techOn && techView && techView.resize) {
      setTimeout(function () { try { techView.resize(); } catch (e) { /* gone */ } }, 30);
    }
  }

  function technicalToggle() {
    if (!techOn) {
      techMount().then(function () {
        techShowFace(true);
        /* Re-stamp on the way in: the pane can be reopened already wide
           from a remembered choice, and the rail would not know. */
        techWideSet(techWide);
      });
    } else {
      techShowFace(false);
      /* [#1389] The pane is gone, so the tabs are nobody's problem any
         more - they come back whatever `wide` is remembered as. */
      try {
        document.documentElement.classList.remove('pine-tech-wide');
      } catch (e) { /* never throw on the way out */ }
    }
  }

  /* Tapping a name in the script traces THAT line, here, without taking
     the show off the glass. */
  function technicalTrace(lineId, said) {
    if (!lineId) return;
    techMount().then(function (view) {
      techShowFace(true);
      if (view && view.showLine) view.showLine(lineId, said);
    });
  }
  root.PineTechnical = {trace: technicalTrace, toggle: technicalToggle};

  /* [#1386] ANY NAME, ANY TITLE, ANY SECTION.
   *
   * "whenever I tap on a title or any name or a section inside of the
   *  script view, I want the feed to become a visual node editor."
   *
   * ONE delegated listener rather than a handle sewn onto each renderer.
   * The screenplay is built out of `.sp-el` elements - scene, character,
   * dialogue, parenthetical, action - and a dialogue element carries its
   * `data-line`. A character heading has none of its own, because a name
   * is not a line; the line it names is the next element down, which is
   * exactly what sayingWho() walks backwards to find. So: take the id off
   * whichever element was tapped, or off the first one below it that has
   * one.
   *
   * Delegated also means it keeps working for every element the script
   * grows later without anybody remembering to wire it up. */
  function techIdNear(node) {
    var at = node;
    for (var up = 0; at && up < 4; up += 1) {
      if (at.classList && at.classList.contains('sp-el')) break;
      at = at.parentNode;
    }
    if (!at || !at.classList || !at.classList.contains('sp-el')) return null;
    /* A REAL line id, not a plan key. The screenplay carries two kinds of
       `data-line`: an aired line's own 32-character id, and the planner's
       composite key for an entry that has not happened yet (`seg:c3`).
       The ledger only knows the first, and answering "that line is not in
       the ledger" for a row that was never a line is a true sentence that
       helps nobody. So a short or punctuated key is skipped and the walk
       carries on to the next element that has a real one. */
    var REAL = /^[0-9a-f]{24,}$/i;
    var own = at.getAttribute && at.getAttribute('data-line');
    if (own && REAL.test(own)) {
      return {id: own, said: String(at.textContent || '')};
    }
    /* A heading, a scene or a cue: the line it introduces is below it. */
    var walk = at.nextElementSibling;
    for (var down = 0; walk && down < 6; down += 1) {
      var got = walk.getAttribute && walk.getAttribute('data-line');
      if (got && REAL.test(got)) {
        return {id: got, said: String(walk.textContent || '')};
      }
      walk = walk.nextElementSibling;
    }
    return null;
  }

  if (root.document) root.document.addEventListener('click', function (ev) {
    var node = ev.target;
    if (!node || !node.closest) return;
    /* Not while something is being edited or dragged over the script, and
       never over the technical pane itself - a tap on a node there is the
       graph's own. */
    if (node.closest('.wc-dialog') || node.closest('input')
        || node.closest('textarea') || node.closest('button')) return;
    var el2 = node.closest('.sp-el');
    if (!el2) return;
    var got = techIdNear(el2);
    if (!got) return;
    technicalTrace(got.id, got.said);
  }, true);

  function segReveal(lineId, seat) {
    var card = segCardFor(lineId) || (seat ? segCardForSeat(seat) : null);
    if (!card) {
      segSay(lineId
        ? 'That line is not in the list under this window.'
        : 'The station recorded no line for ' + segSeatLook(seat).label
          + ' inside this block.');
      return false;
    }
    try { card.scrollIntoView({block: 'center'}); } catch (err) { /* no scroller */ }
    card.classList.remove('sp-segflash');
    /* Read a layout property so the animation restarts when the same card
       is tapped twice; without it the second tap does nothing visible. */
    try { void card.offsetWidth; } catch (err) { /* headless */ }
    card.classList.add('sp-segflash');
    setTimeout(function () { card.classList.remove('sp-segflash'); }, 1300);
    segDetailOpen(card, true);
    return true;
  }

  /* Wire one chain element - a seat chip or an arrow - to the line it
     stands for. `tie` is the hand-off row; a chip that follows an arrow is
     the seat that ANSWERED, so the arrow's line_id is that chip's line. */
  function segFlowTap(node, seat, tie) {
    if (!node || !node.addEventListener) return;
    var lid = String((tie && tie.line_id) || '');
    node.classList.add('sp-segflow-tap');
    node.setAttribute('role', 'button');
    node.setAttribute('tabindex', '0');
    node.title = lid
      ? 'Show this line in the list'
      : 'Show ' + segSeatLook(seat).label + '’s first line in the list';
    var go = function (ev) {
      if (ev) { ev.preventDefault(); ev.stopPropagation(); }
      segReveal(lid, seat);
    };
    node.addEventListener('click', go);
    node.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
      go(ev);
    });
  }

  /* ------------------------------------------- #1238: the detail card */

  /* EVERYTHING THE STATION HOLDS ABOUT ONE LINE, under the line.
   *
   * Not a second pop-up: a window on top of a window is a window the
   * operator has to close twice, and the thing he is comparing it against
   * is the thing it would be covering. It unfolds in place, and folds away
   * when the row is tapped again on its own head.
   *
   * Half of these fields exist because #1194 taught segment_inspect to
   * carry them: the sample behind a sting and its signed road, the take
   * (the pantry key the render cache knows the audio by), the media file,
   * the delivery it rode, and whether this line is ITSELF a replay. On a
   * station without that patch they are simply absent, and absent prints
   * as absent - this window has never been allowed to invent a field. */
  function segDetailOpen(card, force) {
    if (!card) return;
    var had = card.querySelector('.sp-segdeep');
    if (had) {
      if (force) return;                 /* already unfolded: leave it */
      had.remove();
      card.classList.remove('sp-segopen');
      return;
    }
    var l = segLineOf(card.getAttribute('data-line-id')) || card.pineLine || {};
    var look = segSeatLook(l.who);
    var deep = make('div', 'sp-segdeep');
    deep.appendChild(make('div', 'sp-segdeep-h', 'What the station holds about this line'));

    segRow(deep, 'seat', look.label + (segHas(l.who) ? '  ·  ' + l.who : ''),
      segHas(l.name) ? 'named ' + l.name : '');
    segRow(deep, 'voice', l.voice, segHas(l.voice) ? '' : 'no voice id was recorded');
    segRow(deep, 'engine', l.engine, segHas(l.engine) ? '' : 'the ledger did not record which engine spoke it');
    segRow(deep, 'model', l.model);
    segRow(deep, 'length', segSecs(l.seconds), segHas(l.seconds) ? '' : 'never measured');
    segRow(deep, 'air time', segHas(l.at) ? l.at : null,
      segHas(l.air_at) ? 'air_at ' + l.air_at : 'the station gave it no air time');

    /* HEARD IS THE TRUTHFUL ONE. published is a hand-over; heard is an
       acknowledgement, and the two are different answers. */
    var heard = l.heard === true ? 'heard'
      : (l.heard === false ? 'never heard' : 'the station did not say');
    var why = '';
    if (l.heard === true && segHas(l.heard_at)) why = 'at ' + l.heard_at;
    else if (l.heard === false) {
      why = segHas(l.withdrawn_why)
        ? 'refused at hand-over: ' + l.withdrawn_why
        : (l.published
          ? 'handed over and never acknowledged'
          : 'it was written and never handed over');
      if (segHas(segShown && segShown.heard_basis)) {
        why += '  ·  basis: ' + segShown.heard_basis;
      }
    }
    var hr = segRow(deep, 'heard', heard, why);
    if (l.heard === false) hr.classList.add('sp-seghole');
    segRow(deep, 'aired', l.aired, segHas(l.aired) ? '' : 'nothing was recorded');
    segRow(deep, 'scripted', l.scripted === false ? 'no' : (l.scripted === true ? 'yes' : null),
      l.scripted === false ? 'welded on afterwards, not written into the running order' : '');

    segRow(deep, 'source document', l.source,
      segHas(l.source) ? '' : 'no document was recorded behind these words');
    segRow(deep, 'block / ord',
      (segHas(segShown && segShown.block) ? segShown.block : '?')
        + ' / ' + (segHas(l.ord) ? l.ord : '?'),
      'the pair the ledger orders the script by (#1330)');
    segRow(deep, 'line id', l.line_id);

    /* #1194's handles. The sample for a sting, the file for a spoken line,
       and the take - three different ways to find the same audio. */
    if (segIsSting(l)) {
      segRow(deep, 'the sample', l.sfx,
        segHas(l.sfx) ? 'the id the /sfx/ road serves'
          : 'the station could not name the sample behind this sting');
    }
    segRow(deep, 'audio file', l.media || l.clip_media,
      (segHas(l.clip_from) || segHas(l.clip_until))
        ? ('cut from ' + segWord(l.clip_from, '?') + ' to ' + segWord(l.clip_until, '?'))
        : (segHas(l.media) || segHas(l.clip_media) ? '' : 'nothing on disk is named for it'));
    segRow(deep, 'the take', l.take,
      segHas(l.take) ? 'the pantry key - engine, voice and words, hashed'
        : 'this line was not rendered from a take');
    segRow(deep, 'delivery', l.delivery_id);
    if (l.replay) {
      segRow(deep, 'this is a replay', 'yes',
        segHas(l.replay_of) ? 'of line ' + l.replay_of : '');
    }
    if (l.video) segRow(deep, 'it had a picture', 'yes');

    deep.appendChild(segReplayButton(card, l));
    card.appendChild(deep);
    card.classList.add('sp-segopen');
  }

  /* ------------------------------------------- #1194: say it again, live */

  function segReplayButton(card, l) {
    var row = make('div', 'sp-segdeep-do');
    var b = make('button', 'sp-segdeep-play', '');
    b.type = 'button';
    var ico = folderIcon('c:volume--up--filled', 'Say it again');
    b.innerHTML = (ico ? ico + ' ' : '') + 'Say it again, on the broadcast';
    b.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      segLineReplay(card, l);
    });
    row.appendChild(b);
    row.appendChild(make('span', 'sp-segdeep-note',
      'every page and the box, not this speaker'));
    return row;
  }

  /* "tap each one in order to play its sound ON THE BROADCAST."
   *
   * The hold sheet's own "Play it" is deliberately left alone: that one
   * says "hear this line, here", for one pair of ears. This is the other
   * thing, and it is the whole point of the request - the page feed every
   * listener drains and the box. The road is POST /api/script/line/replay
   * (app.py, #1194), which re-admits the line, appends it to the page feed
   * and hands it to the box, and writes a fresh ring row marked
   * `replay`/`replay_of` so the ledger can tell a line said twice from a
   * line said once. */
  function segLineReplay(card, l) {
    var lid = String((l && l.line_id) || '');
    if (!lid) {
      segSay('The station gave this line no id, so it cannot be played again.');
      return;
    }
    if (segReplaying) {
      segSay(segReplaying === lid
        ? 'that one is already going out'
        : 'one line is already on its way to the air');
      return;
    }
    if (!api() || !api().post) {
      segSay('There is no bridge to the station from this surface.');
      return;
    }
    segReplaying = lid;
    card.classList.add('sp-segsending');
    segSay('putting it back on the air…', true);
    Promise.resolve(api().post('/api/script/line/replay',
      {line_id: lid, block: (segShown && segShown.block) || 0})).then(function (got) {
        segReplaying = '';
        card.classList.remove('sp-segsending');
        card.classList.add('sp-segsaid');
        setTimeout(function () { card.classList.remove('sp-segsaid'); }, 2600);
        segSay(String((got && got.say) || 'said again on every page'));
      }, function (err) {
        segReplaying = '';
        card.classList.remove('sp-segsending');
        segSay('it did not go out: ' + segWhy(err), true);
      });
  }

  /* --------------------------------- #1194: the hold sheet, at the finger */

  function segRowSheet(card, l, x, y) {
    var la = root.PineLineActions;
    var words = card.querySelector('.sp-segline-text');
    if (!la || typeof la.open !== 'function') {
      segSay('This surface has no hold sheet loaded, so there is nothing to open.');
      return;
    }
    var said = String((l && l.text) || (words ? words.textContent : '') || '').trim();
    try {
      la.open({id: String((l && l.line_id) || ''), said: said, node: words || card});
    } catch (err) {
      segSay('the hold sheet would not open: ' + segWhy(err));
      return;
    }
    segSheetAtFinger(x, y);
  }

  /* There is no hover on the tablet and no mouse for the sheet to follow,
     so it is put where the finger is - and clamped inside the glass,
     because a menu half off the screen is a menu with items nobody can
     reach. Measured twice: the sheet grows as its rows land, so the second
     measurement on the next frame is the one that matters. */
  function segSheetAtFinger(x, y) {
    var sheet = document.querySelector('.la-sheet');
    if (!sheet) return;
    /* The action sheet is a modal, not a context menu. Finger-relative
       placement could leave its bottom outside Android's visual viewport,
       especially after the status/navigation bars were inset. The shared
       sheet now owns one safe, centred layout on every dialogue surface. */
    sheet.classList.add('sp-at-finger');
    sheet.style.removeProperty('left');
    sheet.style.removeProperty('top');
    sheet.style.removeProperty('right');
    sheet.style.removeProperty('bottom');
    sheet.style.removeProperty('transform');
  }

  /* ------------------------------------- #1194: the gestures on one row */

  function segRowForget(card) {
    if (card.pineHoldTimer) clearTimeout(card.pineHoldTimer);
    card.pineHoldTimer = 0;
  }

  /* A TAP, A HOLD AND A SCROLL ARE THREE DIFFERENT THINGS, and getting
     that wrong makes a list impossible to read: the timer dies on any
     movement past a few pixels, the hold marks the press so the release
     is not also read as a tap, and a press that starts inside the unfolded
     detail card belongs to that card's own buttons. */
  function segLineWire(card, l) {
    var lid = String((l && l.line_id) || '');
    card.pineLine = l || {};
    card.setAttribute('data-line-id', lid);
    card.setAttribute('data-seat', String((l && l.who) || ''));
    var words = card.querySelector('.sp-segline-text');
    if (words && segIsSting(l)) {
      /* #1200 reads this to know a sound-effect row when it sees one, and
         to offer the trash can that belongs only to those. */
      words.pineItem = {tag: 'sting', sfx: String((l && l.sfx) || ''),
        line: lid, deleted: false, text: String((l && l.text) || '')};
    }
    if (!lid) {
      card.classList.add('sp-segline-mute');
      card.title = 'The station gave this line no id, so it cannot be'
        + ' played again or looked up.';
      return;
    }
    card.classList.add('sp-segtap');
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.title = 'Tap: say it again on the broadcast. Hold or right-click:'
      + ' what can be done with it.';
    var press = null;
    card.addEventListener('pointerdown', function (ev) {
      if (ev.button !== undefined && ev.button > 0) return;   /* the right button */
      if (ev.target && ev.target.closest && ev.target.closest('.sp-segdeep')) return;
      segRowForget(card);
      press = {x: ev.clientX || 0, y: ev.clientY || 0, held: false};
      card.pineHoldTimer = setTimeout(function () {
        card.pineHoldTimer = 0;
        if (!press) return;
        press.held = true;
        segRowSheet(card, card.pineLine, press.x, press.y);
      }, SEG_HOLD_MS);
    });
    card.addEventListener('pointermove', function (ev) {
      if (!press) return;
      if (Math.abs((ev.clientX || 0) - press.x) > SEG_HOLD_SLOP
          || Math.abs((ev.clientY || 0) - press.y) > SEG_HOLD_SLOP) {
        segRowForget(card);
        press = null;                                   /* a scroll, not a hold */
      }
    });
    card.addEventListener('pointerup', function (ev) {
      segRowForget(card);
      var was = press;
      press = null;
      if (!was || was.held) return;
      if (ev.target && ev.target.closest && ev.target.closest('.sp-segdeep')) return;
      segLineReplay(card, card.pineLine);
    });
    card.addEventListener('pointercancel', function () {
      segRowForget(card);
      press = null;
    });
    /* The desk has a second button and that is what it is for. */
    card.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      segRowForget(card);
      press = null;
      segRowSheet(card, card.pineLine, ev.clientX, ev.clientY);
    });
    /* At the desk there is a keyboard, and a role="button" that cannot be
       worked from it is a button in name only. Enter says it again; the
       space bar unfolds what the station holds about it. */
    card.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); segLineReplay(card, card.pineLine); }
      else if (ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        segDetailOpen(card, false);
      }
    });
  }

  /* ------------------------------------------------ #1235: the itinerary */

  /* "[the script heading] When I tap on that I want to see the full
   * itinerary."
   *
   * The heading already had a HOLD on it (#1164: complain, mark an issue,
   * report a missing segment) and a tap did nothing at all except shut that
   * menu again. A tap now opens the hour's running order - the sheet the
   * script is being performed FROM - with the next hour under it.
   *
   * /api/director?hour=N is that running order and nothing here re-derives
   * it: the times, the kinds, the durations, what is banked behind each
   * entry, what aired out of it and what is still to come are all the
   * station's own fields. The pane at the bottom of the script shows the
   * same source but only what is STILL TO COME; this shows the whole hour,
   * which is what "full itinerary" asks for.
   *
   * The hold is untouched. A tap is a tap and a hold is a hold, and #1164's
   * menu is still the thing a hold raises. */
  var ITIN_ID = 'spItinerary';

  function itineraryClose() { var n = el(ITIN_ID); if (n) n.remove(); }

  function activeSegment(row) {
    var id = String((row && row.id) || nowLineId || '');
    var node = id ? lineNode(id) : null;
    while (node && !/(^|\s)sp-scene(\s|$)/.test(String(node.className || ''))) {
      node = node.previousElementSibling;
    }
    return node ? segIdentity(node) : null;
  }

  function itineraryOpen(target) {
    var current = activeSegment(activeRow());
    var sheet = sheetShell(ITIN_ID, 'sp-itin', current && current.heading
      ? 'On air: ' + current.heading : 'The station calendar');
    /* A diagnostic surface: the broadcast ducks while it is open and lets
       go by itself when the sheet leaves the page. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-' + ITIN_ID, root.PineDuck.REPORT, sheet.back);
    }
    var name = el('spScriptHead');
    sheet.box.appendChild(make('div', 'sp-itin-what',
      name ? headerText(name) : 'the broadcast'));
    var tools = make('div', 'sp-itin-tools');
    var views = make('div', 'sp-itin-views');
    var list = make('div', 'sp-itin-list');
    function tab(label, mode) {
      var button = make('button', 'sp-itin-tab', label);
      button.type = 'button';
      button.addEventListener('click', function () {
        Array.prototype.forEach.call(views.querySelectorAll('.sp-itin-tab'), function (one) {
          one.classList.toggle('on', one === button);
        });
        if (mode === 'hour') itineraryHour(list, sheet);
        else itineraryCalendar(list, sheet, mode);
      });
      views.appendChild(button);
      return button;
    }
    var hourTab = tab('Hour', 'hour');
    tab('Day', 'day'); tab('Week', 'week'); tab('Month', 'month');
    hourTab.classList.add('on');
    tools.appendChild(views);
    var add = make('button', 'sp-itin-add', '+ Segment');
    add.type = 'button';
    add.addEventListener('click', function () { itineraryAdd(list, sheet); });
    tools.appendChild(add);
    var copy = make('button', 'sp-itin-add', 'Copy schedule');
    copy.type = 'button';
    copy.title = 'Make an editable copy of the current schedule before trying a new running order';
    copy.addEventListener('click', function () { itineraryCopySchedule(sheet); });
    tools.appendChild(copy);
    sheet.box.appendChild(tools);
    sheet.box.appendChild(list);
    sheet.revealLive = true;
    sheet.revealEntry = target && typeof target === 'object' ? target : null;
    itineraryHour(list, sheet);
    return sheet;
  }

  function itineraryHour(list, sheet) {
    list.replaceChildren();
    list.appendChild(make('div', 'sp-itin-wait',
      'asking the station for the running order…'));
    if (!api() || !api().get) {
      list.textContent = '';
      list.appendChild(make('div', 'sp-segrow-why',
        'There is no bridge to the station from this surface.'));
      return sheet;
    }
    var want = [
      Promise.resolve(api().get('/api/director?hour=0')).then(null, function () { return null; }),
      Promise.resolve(api().get('/api/director?hour=1')).then(null, function () { return null; })
    ];
    Promise.all(want).then(function (got) {
      if (!el(ITIN_ID)) return;                       /* closed while asking */
      var fresh = got.filter(Boolean);
      /* #1289b's rule, for the same reason: a blip must not WIPE the
         running order this terminal already holds. */
      if (fresh.length) {
        got.forEach(function (page, index) {
          if (page) planHours[index] = page;
        });
        planAt = Date.now();
        paintPlan();
      }
      var hours = planHours.filter(Boolean);
      list.textContent = '';
      if (!hours.length) {
        list.appendChild(make('div', 'sp-segrow-why', 'The station did not'
          + ' answer for the running order, and this terminal holds none.'));
        return;
      }
      itineraryPaint(list, hours, sheet);
      if (sheet.revealEntry) {
        var wanted = sheet.revealEntry;
        sheet.revealEntry = null;
        var match = Array.prototype.find.call(list.querySelectorAll('.sp-itin-row'),
          function (row) {
            return wanted.occurrence
              ? row.dataset.occurrence === String(wanted.occurrence)
              : row.dataset.slot === String(wanted.slot_id || '');
          });
        if (match && typeof match.__pineOpen === 'function') {
          match.__pineOpen(true);
          match.scrollIntoView({block: 'center'});
          sheet.revealLive = false;
        } else {
          sheet.revealLive = false;
          sheet.say('That segment is no longer in the current running order.', true);
        }
      }
      if (sheet.revealLive) {
        sheet.revealLive = false;
        itineraryRevealLive(list);
      }
      if (!fresh.length) {
        sheet.say('The station did not answer just now - this is the running'
          + ' order as it last stood here.', true);
      }
    });
  }

  function itinPresetSelect(names, value, onChange) {
    var pick = document.createElement('select');
    pick.className = 'sp-itin-preset';
    (names || []).forEach(function (name) {
      var option = make('option', '', String(name));
      option.value = String(name);
      option.selected = String(name) === String(value || '');
      pick.appendChild(option);
    });
    pick.addEventListener('change', function () { onChange(pick.value, pick); });
    return pick;
  }

  function itineraryCalendar(list, sheet, mode) {
    list.replaceChildren(make('div', 'sp-itin-wait', 'reading the calendar…'));
    var many = mode === 'week' ? 7 : mode === 'month' ? 31 : 0;
    var reads = [api().get('/api/schedule')];
    if (many) {
      var today = new Date();
      var key = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0')
        + '-' + String(today.getDate()).padStart(2, '0');
      reads.push(api().get('/api/schedule/month?from=' + key + '&days=' + many));
    }
    Promise.all(reads).then(function (got) {
      if (!el(ITIN_ID)) return;
      var state = got[0] || {};
      var names = state.presets || [];
      list.replaceChildren();
      if (mode === 'day') {
        list.appendChild(make('div', 'sp-itin-calendar-head',
          'Every hour · changes apply on the next initialization of that hour'));
        for (var hour = 0; hour < 24; hour += 1) {
          (function (h) {
            var row = make('div', 'sp-itin-calendar-row');
            row.appendChild(make('b', '', String(h).padStart(2, '0') + ':00'));
            row.appendChild(itinPresetSelect(names, (state.day || {})[String(h)],
              function (value, pick) {
                pick.disabled = true;
                var hours = {}; hours[String(h)] = value;
                api().post('/api/schedule/day', {hours: hours}).then(function () {
                  sheet.say(String(h).padStart(2, '0') + ':00 now runs ' + value);
                  pick.disabled = false;
                }, function (err) {
                  pick.disabled = false; sheet.say((err && err.message) || err, true);
                });
              }));
            list.appendChild(row);
          })(hour);
        }
        return;
      }
      var plan = got[1] || {};
      list.appendChild(make('div', 'sp-itin-calendar-head',
        (mode === 'week' ? 'Seven days' : 'Thirty-one days')
        + ' · auto means the day inherits the hourly plan'));
      (plan.month || []).forEach(function (day) {
        var row = make('div', 'sp-itin-calendar-row');
        var stamp = make('b', '', String(day.date || ''));
        if (day.auto) stamp.appendChild(make('i', '', ' auto'));
        row.appendChild(stamp);
        row.appendChild(itinPresetSelect(names, day.preset, function (value, pick) {
          pick.disabled = true;
          var days = {}; days[String(day.date || '')] = value;
          api().post('/api/schedule/month', {days: days}).then(function () {
            stamp.classList.add('saved');
            sheet.say(String(day.date || '') + ' now runs ' + value);
            pick.disabled = false;
          }, function (err) {
            pick.disabled = false; sheet.say((err && err.message) || err, true);
          });
        }));
        list.appendChild(row);
      });
    }, function (err) {
      list.replaceChildren(make('div', 'sp-segrow-why',
        'The calendar did not answer: ' + ((err && err.message) || err)));
    });
  }

  function itineraryAdd(list, sheet) {
    list.replaceChildren(make('div', 'sp-itin-wait', 'reading the active schedule…'));
    api().get('/api/schedule').then(function (state) {
      list.replaceChildren();
      var form = make('form', 'sp-itin-new');
      form.appendChild(make('b', '', 'Add a segment to ' + String(state.active || 'the schedule')));
      var kind = document.createElement('select');
      (state.kinds || []).forEach(function (row) {
        var option = make('option', '', String(row.label || row.kind));
        option.value = String(row.kind || ''); kind.appendChild(option);
      });
      var label = document.createElement('input');
      label.placeholder = 'segment name'; label.required = true;
      var minutes = document.createElement('input');
      minutes.type = 'number'; minutes.min = '.25'; minutes.max = '60';
      minutes.step = '.25'; minutes.value = '3';
      var save = make('button', '', 'Add to the running order'); save.type = 'submit';
      form.appendChild(kind); form.appendChild(label); form.appendChild(minutes); form.appendChild(save);
      form.addEventListener('submit', function (event) {
        event.preventDefault(); save.disabled = true;
        var slots = (state.slots || []).slice();
        slots.push({id: '', kind: kind.value, label: label.value,
          minutes: Number(minutes.value) || 3, enabled: true});
        api().post('/api/schedule/slots', {preset: state.active, slots: slots})
          .then(function () {
            sheet.say('Added ' + label.value + ' to ' + state.active);
            itineraryHour(list, sheet);
          }, function (err) {
            save.disabled = false; sheet.say((err && err.message) || err, true);
          });
      });
      list.appendChild(form);
    }, function (err) {
      list.replaceChildren(make('div', 'sp-segrow-why',
        'The schedule did not answer: ' + ((err && err.message) || err)));
    });
  }

  function itineraryCopySchedule(sheet) {
    api().get('/api/schedule').then(function (state) {
      var source = String((state && state.active) || 'schedule');
      var proposed = source + ' copy ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
      var name = root.prompt('Name this editable schedule copy', proposed);
      if (!name || !String(name).trim()) return;
      return api().post('/api/schedule/preset', {name: String(name).trim(), copy_from: source})
        .then(function (got) {
          sheet.say('Saved ' + String((got && got.active) || name)
            + '. Select it on Day, Week or Month when you want it on air.');
        });
    }, function (err) { sheet.say(String((err && err.message) || err), true); })
      ['catch'](function (err) { sheet.say(String((err && err.message) || err), true); });
  }

  function itineraryReorder(entry, before, sheet, done) {
    var moved = String((entry && entry.slot_id) || '');
    var target = String((before && before.slot_id) || '');
    var preset = String((entry && entry.schedule_preset) || '');
    if (!moved || !target || moved === target) return;
    api().get('/api/schedule').then(function (state) {
      var active = preset || String((state && state.active) || '');
      var slots = ((state && state.presets && state.presets[active]) || []).slice();
      var from = slots.findIndex(function (slot) { return String(slot.id || '') === moved; });
      var to = slots.findIndex(function (slot) { return String(slot.id || '') === target; });
      if (from < 0 || to < 0) throw new Error('Those segments are not on the editable schedule.');
      var row = slots.splice(from, 1)[0];
      if (from < to) to -= 1;
      slots.splice(to, 0, row);
      return api().post('/api/schedule/slots', {preset: active, slots: slots});
    }).then(function () {
      sheet.say('Running order saved. The orchestrator will rebuild the affected upcoming segments.');
      if (typeof done === 'function') done();
    }, function (err) { sheet.say(String((err && err.message) || err), true); });
  }

  function itinClock(ts) {
    var n = Number(ts) || 0;
    if (!n) return '';
    try { return new Date(n * 1000).toTimeString().slice(0, 5); } catch (err) { return ''; }
  }

  /* WHICH LINE OF THE SCRIPT AN ENTRY ON THE SHEET IS.
   *
   * The ledger does not record the slot a round was written for - the
   * Segment window says so in the station's own words under "Which entry on
   * the sheet". So the honest link is the CLOCK: the first element on the
   * page whose air time falls inside this entry's window. Where the entry
   * names a road, one written for that road is preferred over one that
   * merely overlaps it, and where nothing falls inside, nothing is claimed:
   * the row says the script holds no line for it yet, which for an entry
   * that has not happened is the truth rather than a gap. */
  function itinFirstLine(entry, until) {
    var from = Number(entry && entry.start) || 0;
    if (!from) return null;
    var to = Number(until) || Number(entry && entry.deadline) || 0;
    if (!to || to <= from) {
      to = from + Math.max(60, (Number(entry && entry.minutes) || 1) * 60);
    }
    var kind = String((entry && entry.kind) || '');
    var loose = null;
    for (var i = 0; i < elements.length; i += 1) {
      var e = elements[i] || {};
      var at = Number(e.at) || 0;
      if (!e.line || at < from || at >= to) continue;
      if (kind && (String(e.kind || '') === kind || String(e.round || '') === kind)) {
        return e;
      }
      if (!loose) loose = e;
    }
    return loose;
  }

  /* What is behind an entry, in one phrase. `turns` is material BOUND to
     it and ready to say; `drafts` is material written and not bound, which
     is not the same promise and must not read like it. */
  function itinBanked(entry) {
    var sc = (entry && entry.script) || {};
    var turns = sc.turns || [];
    if (turns.length) {
      return turns.length + (turns.length === 1 ? ' turn banked' : ' turns banked')
        + (segHas(sc.seconds) ? '  ·  ' + segSecs(sc.seconds) : '');
    }
    var drafts = Number(sc.drafts) || 0;
    if (drafts) {
      return drafts + (drafts === 1 ? ' draft waiting' : ' drafts waiting')
        + ', none bound';
    }
    return 'nothing behind it';
  }

  function itinAired(entry) {
    var rows = (entry && entry.aired) || [];
    var n = rows.length || 0;
    var secs = Number(entry && entry.aired_seconds) || 0;
    if (!n && !secs) return '';
    return (n ? n + (n === 1 ? ' aired feed row' : ' aired feed rows') : 'aired')
      + (secs ? '  ·  ' + segSecs(secs) : '');
  }

  var itinPortraits = {promise: null, bySeat: Object.create(null),
    used: Object.create(null), posters: Object.create(null),
    live: Object.create(null), waiting: Object.create(null)};

  function itinStationUrl(path) {
    var value = String(path || '');
    if (/^https?:/i.test(value)) return value;
    var base = '';
    try {
      base = /^https?:$/i.test(location.protocol) ? location.origin
        : (typeof root.pineStationBase === 'function' ? root.pineStationBase() : '');
    } catch (err) { base = ''; }
    return String(base || '').replace(/\/$/, '') + value;
  }

  function itinPortraitPool() {
    if (itinPortraits.promise) return itinPortraits.promise;
    itinPortraits.promise = Promise.all([
      Promise.resolve(api().get('/api/slideshow?limit=200')).then(null, function () { return {}; }),
      Promise.resolve(api().get('/api/sfx/video/profiles?limit=12')).then(null, function () { return {}; })
    ]).then(function (got) {
        var pictures = ((got[0] && got[0].rows) || []).filter(function (row) {
          return /\.(png|jpe?g|webp|gif)$/i.test(String((row || {}).file || ''))
            && String((row || {}).url || '');
        });
        var motion = ((got[1] && got[1].clips) || []).filter(function (row) {
          return String((row || {}).url || '') && /\.mp4$/i.test(String((row || {}).file || ''));
        }).map(function (row) { return Object.assign({}, row, {motion: true}); });
        return pictures.concat(motion);
      }, function () { return []; });
    return itinPortraits.promise;
  }

  function itinPortraitSeat(turn) {
    var kind = String((turn && turn.kind) || '').toLowerCase();
    var seat = String((turn && turn.seat) || '').toLowerCase();
    if (kind === 'sfx' || kind === 'sfxguy' || seat === 'board' || seat === 'drop') {
      return 'the-sfx-guy';
    }
    return String((turn && (turn.who || turn.seat)) || 'speaker').toLowerCase();
  }

  function itinPortraitAssign(avatar, turn) {
    var key = itinPortraitSeat(turn);
    itinPortraitPool().then(function (pool) {
      if (!pool.length || !avatar || !avatar.isConnected) return;
      var picked = itinPortraits.bySeat[key];
      if (!picked) {
        var start = Math.floor(Math.random() * pool.length);
        for (var i = 0; i < pool.length; i += 1) {
          var candidate = pool[(start + i) % pool.length];
          if (!itinPortraits.used[candidate.file] || i === pool.length - 1) {
            picked = candidate;
            break;
          }
        }
        itinPortraits.bySeat[key] = picked;
        if (picked) itinPortraits.used[picked.file] = true;
      }
      if (!picked) return;
      if (picked.motion) {
        var poster = itinPortraits.posters[key];
        if (poster) {
          var still = document.createElement('img');
          still.alt = ''; still.src = poster;
          avatar.appendChild(still); avatar.classList.add('has-picture');
          return;
        }
        if (itinPortraits.live[key]) {
          (itinPortraits.waiting[key] || (itinPortraits.waiting[key] = [])).push(avatar);
          return;
        }
        var video = document.createElement('video');
        video.style.visibility = 'hidden';
        video.muted = true; video.defaultMuted = true; video.volume = 0;
        video.autoplay = true; video.loop = true; video.playsInline = true;
        video.preload = 'metadata'; video.setAttribute('muted', '');
        video.setAttribute('playsinline', ''); video.setAttribute('aria-hidden', 'true');
        itinPortraits.live[key] = video;
        videoFirstFrame(video, function () {
          video.style.visibility = 'visible';
          avatar.classList.add('has-picture');
          try {
            var canvas = document.createElement('canvas');
            canvas.width = 96; canvas.height = 96;
            var context = canvas.getContext('2d');
            if (context) {
              var sw = video.videoWidth || 96, sh = video.videoHeight || 96;
              var side = Math.min(sw, sh);
              context.drawImage(video, (sw - side) / 2, (sh - side) / 2,
                side, side, 0, 0, 96, 96);
              itinPortraits.posters[key] = canvas.toDataURL('image/jpeg', 0.78);
            }
          } catch (err) { /* the muted live frame remains a valid portrait */ }
          var waiting = itinPortraits.waiting[key] || [];
          waiting.forEach(function (seat) {
            if (!seat || !seat.isConnected || !itinPortraits.posters[key]) return;
            var image = document.createElement('img'); image.alt = '';
            image.src = itinPortraits.posters[key]; seat.appendChild(image);
            seat.classList.add('has-picture');
          });
          itinPortraits.waiting[key] = [];
        }, function () {
          video.style.visibility = 'hidden';
          avatar.classList.remove('has-picture');
        });
        video.addEventListener('error', function () {
          delete itinPortraits.live[key]; video.remove();
        });
        video.src = itinStationUrl(picked.url);
        avatar.appendChild(video);
        Promise.resolve(video.play()).catch(function () {});
        return;
      }
      var image = document.createElement('img');
      image.alt = '';
      image.loading = 'lazy';
      image.addEventListener('load', function () { avatar.classList.add('has-picture'); });
      image.addEventListener('error', function () { image.remove(); });
      image.src = itinStationUrl(picked.url);
      avatar.appendChild(image);
    });
  }

  function itinAvatar(turn) {
    var who = String((turn && (turn.who || turn.seat)) || 'speaker');
    var initials = who.split(/\s+/).filter(Boolean).slice(0, 2)
      .map(function (word) { return word.charAt(0).toUpperCase(); }).join('') || '?';
    var avatar = make('span', 'sp-itin-avatar', initials);
    avatar.setAttribute('aria-hidden', 'true');
    itinPortraitAssign(avatar, turn);
    return avatar;
  }

  function turnCandidateIndex(turn, fallback) {
    var value = turn && turn.candidate_index;
    if (value !== undefined && value !== null && isFinite(Number(value))) {
      return Number(value);
    }
    value = turn && turn.prepared_index;
    return value !== undefined && value !== null && isFinite(Number(value))
      ? Number(value) : Number(fallback) || 0;
  }

  function turnPerformanceIndex(turn) {
    var value = turn && turn.performance_index;
    return value !== undefined && value !== null && isFinite(Number(value))
      ? Number(value) : 0;
  }

  function scriptPerformances(script) {
    script = script || {};
    var bound = Array.isArray(script.turns) ? script.turns : [];
    var turns = bound.length ? bound
      : (Array.isArray(script.draft_turns) ? script.draft_turns : []);
    var supplied = Array.isArray(script.performances) ? script.performances : [];
    var byIndex = Object.create(null);
    supplied.forEach(function (performance, index) {
      performance = performance || {};
      var pi = performance.performance_index;
      if (pi === undefined || pi === null) pi = performance.index;
      pi = pi !== undefined && pi !== null && isFinite(Number(pi)) ? Number(pi) : index;
      byIndex[pi] = {
        index: pi,
        candidate: String(performance.candidate || performance.id || ''),
        seconds: Number(performance.seconds) || 0,
        turns: Array.isArray(performance.turns) ? performance.turns.length
          : (Number(performance.turns || performance.lines) || 0)
      };
    });
    turns.forEach(function (turn) {
      var pi = turnPerformanceIndex(turn);
      var group = byIndex[pi] || {index: pi, candidate: '', seconds: 0, turns: 0};
      if (!group.candidate) group.candidate = String((turn && turn.candidate) || '');
      if (!supplied.length) group.turns += 1;
      byIndex[pi] = group;
    });
    var rows = Object.keys(byIndex).map(function (key) { return byIndex[key]; })
      .sort(function (a, b) { return a.index - b.index; });
    var total = Number(script.seconds) || rows.reduce(function (sum, row) {
      return sum + (Number(row.seconds) || 0);
    }, 0);
    return {rows: rows, seconds: total,
      candidates: Array.isArray(script.candidates) ? script.candidates.slice() : []};
  }

  function turnEditBody(turn, fallback, text) {
    var local = turnCandidateIndex(turn, fallback);
    return {index: local, candidate_index: local,
      performance_index: turnPerformanceIndex(turn),
      text: String(text || ''), was: String((turn && turn.text) || ''),
      candidate: String((turn && turn.candidate) || '')};
  }

  function itinConversationTurns(entry, variant) {
    var script = (entry && entry.script) || {};
    var bound = script.turns || [];
    var prepared = variant ? (variant.turns || [])
      : (bound.length ? bound : (script.draft_turns || []));
    var aired = (entry && entry.aired) || [];
    var turns = [];
    var heard = [];
    function words(value) { return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
    function sameSeat(turn, row, requireSeat) {
      var seats = {A: ['dj', 'host'], B: ['cohost'], C: ['caller'],
        D: ['third'], E: ['caller2']};
      var expected = seats[String((turn && turn.seat) || '').toUpperCase()];
      var actual = String((row && row.who) || '').toLowerCase();
      if (requireSeat && (!expected || !actual)) return false;
      return !expected || !actual || expected.indexOf(actual) !== -1;
    }
    function speech(row) {
      var kind = String((row && row.kind) || '').toLowerCase();
      var who = String((row && row.who) || '').toLowerCase();
      return kind !== 'sfx' && kind !== 'sting' && kind !== 'sfxguy'
        && kind !== 'marker' && who !== 'board' && who !== 'drop';
    }
    function consume(turn, target) {
      var i, j, phrase;
      for (i = 0; i < heard.length; i += 1) {
        if (heard[i].used || heard[i].text !== target || !speech(heard[i].row)
            || !sameSeat(turn, heard[i].row, false)) continue;
        heard[i].used = true;
        return true;
      }
      if (!bound.length || variant) return false;
      for (i = 0; i < heard.length; i += 1) {
        if (heard[i].used || !speech(heard[i].row)
            || !sameSeat(turn, heard[i].row, true)) continue;
        phrase = heard[i].text;
        if (!target.startsWith(phrase + ' ')) continue;
        for (j = i + 1; j < Math.min(heard.length, i + 4); j += 1) {
          if (heard[j].used || !speech(heard[j].row)
              || !sameSeat(turn, heard[j].row, true)) break;
          phrase += ' ' + heard[j].text;
          if (phrase === target) {
            for (var used = i; used <= j; used += 1) heard[used].used = true;
            return true;
          }
          if (!target.startsWith(phrase + ' ')) break;
        }
      }
      return false;
    }
    aired.forEach(function (row) {
      var text = String((row || {}).text || '').trim();
      if (!text) return;
      var kind = String(row.kind || '').toLowerCase();
      var seat = String(row.who || '');
      var who = String(row.name || seat || 'speaker');
      if (kind === 'sfx') who = 'The SFX Guy - stinger';
      else if (kind === 'sfxguy' || seat === 'drop') who = 'The SFX Guy';
      turns.push({seat: seat, who: who, text: text, kind: kind,
        line: String(row.line || ''), at: row.at, aired: true});
      heard.push({row: row, text: words(text), used: false});
    });
    prepared.forEach(function (turn, index) {
      var text = String((turn || {}).text || '').trim();
      if (!text) return;
      var fingerprint = words(text);
      if (consume(turn, fingerprint)) return;
      var local = turnCandidateIndex(turn, index);
      var performance = turnPerformanceIndex(turn);
      var previous = '';
      for (var back = index - 1; back >= 0; back -= 1) {
        if (turnPerformanceIndex(prepared[back]) !== performance) continue;
        previous = String((prepared[back] || {}).text || '');
        break;
      }
      turns.push(Object.assign({}, turn, {text: text, prepared_index: index,
        candidate_index: local, performance_index: performance,
        draft: !!variant || !bound.length,
        candidate: String((variant && variant.id) || turn.candidate || script.candidate || ''),
        previous: previous}));
    });
    var cues = (variant && variant.sfx_plan) || script.sfx_plan || [];
    cues.forEach(function (cue) {
      var after = Math.max(0, Math.min(turns.length, Number(cue.after) + 1));
      turns.splice(after, 0, Object.assign({}, cue, {
        planned_sfx: true, draft: !!variant || !bound.length,
        candidate: String((variant && variant.id) || script.candidate || '')}));
    });
    return turns;
  }

  function itinConversationSections(turns) {
    return {
      heard: turns.filter(function (turn) { return !!turn.aired; }),
      planned: turns.filter(function (turn) { return !turn.aired; })
    };
  }

  function itinFact(table, label, value) {
    if (value === undefined || value === null || value === '') return;
    var tr = document.createElement('tr');
    tr.appendChild(make('th', '', label));
    tr.appendChild(make('td', '', typeof value === 'string'
      ? value : JSON.stringify(value, null, 2)));
    table.appendChild(tr);
  }

  var itinThreePromise = null;
  function itinThree() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (itinThreePromise) return itinThreePromise;
    itinThreePromise = new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = techUrl('/vendor/three.min.js');
      tag.addEventListener('load', function () { resolve(root.THREE); });
      tag.addEventListener('error', function () { reject(new Error('three.js unavailable')); });
      document.head.appendChild(tag);
    });
    return itinThreePromise;
  }

  function itinTurnFlow(canvas) {
    itinThree().then(function (THREE) {
      if (!canvas || !canvas.isConnected || !THREE) return;
      var renderer = new THREE.WebGLRenderer({canvas: canvas, alpha: true, antialias: true});
      renderer.setPixelRatio(Math.min(2, root.devicePixelRatio || 1));
      var width = Math.max(280, canvas.clientWidth || 640);
      var height = Math.max(150, canvas.clientHeight || 180);
      renderer.setSize(width, height, false);
      var scene = new THREE.Scene();
      var camera = new THREE.PerspectiveCamera(38, width / height, .1, 50);
      camera.position.set(0, 0, 11);
      var material = new THREE.MeshBasicMaterial({color: 0x65c7da});
      var lastMaterial = new THREE.MeshBasicMaterial({color: 0xe3be63});
      var geometry = new THREE.BoxGeometry(.72, .72, .72);
      var points = [-3, -1, 1, 3].map(function (x, index) {
        var node = new THREE.Mesh(geometry, index === 3 ? lastMaterial : material);
        node.position.set(x, 0, index * .12 - .2); scene.add(node); return node;
      });
      var pathData = new Float32Array(18);
      var pathGeometry = new THREE.BufferGeometry();
      pathGeometry.setAttribute('position', new THREE.BufferAttribute(pathData, 3));
      var pathMaterial = new THREE.LineBasicMaterial({color: 0x4f7f88, transparent: true, opacity: .8});
      var path = new THREE.LineSegments(pathGeometry, pathMaterial); scene.add(path);
      var pulse = new THREE.Mesh(new THREE.SphereGeometry(.13, 10, 8),
        new THREE.MeshBasicMaterial({color: 0xffffff})); scene.add(pulse);
      var started = performance.now();
      function frame(now) {
        if (!canvas.isConnected) {
          geometry.dispose(); pathGeometry.dispose(); material.dispose();
          lastMaterial.dispose(); pathMaterial.dispose(); renderer.dispose(); return;
        }
        var seconds = (now - started) / 1000;
        points.forEach(function (node, index) {
          node.position.y = Math.sin(seconds * 1.25 + index * .8) * .28;
          node.rotation.x = seconds * .18 + index; node.rotation.y = seconds * .24;
        });
        for (var i = 0; i < 3; i += 1) {
          var at = i * 6;
          pathData[at] = points[i].position.x; pathData[at + 1] = points[i].position.y;
          pathData[at + 2] = points[i].position.z;
          pathData[at + 3] = points[i + 1].position.x; pathData[at + 4] = points[i + 1].position.y;
          pathData[at + 5] = points[i + 1].position.z;
        }
        pathGeometry.attributes.position.needsUpdate = true;
        var travel = (seconds * .36) % 1;
        var segment = Math.min(2, Math.floor(travel * 3));
        var local = travel * 3 - segment;
        pulse.position.lerpVectors(points[segment].position, points[segment + 1].position, local);
        renderer.render(scene, camera);
        root.requestAnimationFrame(frame);
      }
      root.requestAnimationFrame(frame);
    }, function () {
      if (canvas) canvas.classList.add('sp-itin-flow-unavailable');
    });
  }

  function itinTurnOpen(entry, turn, index, refresh) {
    var script = (entry && entry.script) || {};
    var aired = !!turn.aired;
    var draft = !aired && (!((script.turns || []).length) || !!turn.draft);
    var detail = sheetShell('spItinTurn', 'sp-itin-turn',
      String(turn.who || turn.seat || 'Prepared line'));
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-spItinTurn', root.PineDuck.REPORT, detail.back);
    }
    var editor = document.createElement('textarea');
    editor.className = 'sp-itin-turn-edit';
    editor.value = String(turn.text || '');
    editor.readOnly = aired || !!turn.planned_sfx;
    editor.setAttribute('aria-label', aired ? 'Aired line'
      : (draft ? 'Draft line' : 'Edit prepared line'));
    detail.box.appendChild(editor);

    var flow = make('section', 'sp-itin-flow');
    flow.appendChild(make('b', 'sp-itin-flow-title', 'How this line was generated'));
    var canvas = document.createElement('canvas');
    canvas.className = 'sp-itin-flow-canvas';
    canvas.setAttribute('aria-label', 'Animated source flow from seed through topic and prior line to this line');
    flow.appendChild(canvas);
    var legend = make('div', 'sp-itin-flow-legend');
    ['seed and sources', 'active topic', 'previous line', 'this line'].forEach(function (label) {
      legend.appendChild(make('span', '', label));
    });
    flow.appendChild(legend);
    detail.box.appendChild(flow);
    itinTurnFlow(canvas);

    var variant = (script.draft_variants || []).find(function (item) {
      return String(item.id || '') === String(turn.candidate || '');
    }) || {};

    var table = make('table', 'sp-itin-turn-table');
    itinFact(table, 'Segment', entry.label || entry.kind);
    itinFact(table, 'Scheduled', itinClock(entry.start));
    itinFact(table, 'Slot', entry.slot_id);
    itinFact(table, 'Occurrence', entry.occurrence);
    itinFact(table, 'Road', entry.kind);
    itinFact(table, 'Seat', turn.seat);
    itinFact(table, 'Kind', turn.kind);
    itinFact(table, 'Line', turn.line);
    itinFact(table, 'Aired at', turn.at ? itinClock(turn.at) : '');
    itinFact(table, 'Prepared state', script.state);
    itinFact(table, 'Candidate', script.candidate);
    itinFact(table, 'Draft candidate', turn.candidate);
    if (!aired) {
      itinFact(table, 'Performance', turnPerformanceIndex(turn) + 1);
      itinFact(table, 'Line in performance', turnCandidateIndex(turn, index) + 1);
    }
    itinFact(table, 'Source', script.source);
    itinFact(table, 'Source evidence', variant.source || script.source_evidence);
    itinFact(table, 'Active topic', variant.topic || script.topic);
    itinFact(table, 'Topic continuity', variant.topic_review || script.topic_review);
    itinFact(table, 'Prompt and scheduling setup', entry.prompt);
    itinFact(table, 'Direction', entry.direction);
    itinFact(table, 'Beats', entry.beats);
    itinFact(table, 'Tint', script.tint);
    itinFact(table, 'Review', entry.review);
    detail.box.appendChild(table);

    var actions = make('div', 'sp-itin-turn-actions');
    if (aired) {
      if (turn.line) {
        var inspect = make('button', 'sp-itin-turn-save', 'Inspect full provenance');
        inspect.type = 'button';
        inspect.addEventListener('click', function () {
          technicalTrace(String(turn.line || ''), String(turn.text || ''));
        });
        actions.appendChild(inspect);
      } else {
        actions.appendChild(make('span', 'sp-itin-turn-draft',
          'This aired event has no retained line id to trace.'));
      }
    } else if (!turn.planned_sfx) {
      var save = make('button', 'sp-itin-turn-save',
        draft ? 'Save draft rewrite' : 'Save and re-record this line');
      save.type = 'button';
      save.addEventListener('click', function () {
        var said = String(editor.value || '').trim();
        if (!said) { detail.say('A blank line would be a deletion.', true); return; }
        save.disabled = true;
        api().post('/api/director/segment/' + encodeURIComponent(entry.occurrence) + '/turn',
          turnEditBody(turn, index, said)).then(function (got) {
          turn.text = said;
          detail.say(String((got && got.say) || 'Saved.'));
          if (typeof refresh === 'function') refresh();
          setTimeout(detail.close, 900);
        }, function (err) {
          save.disabled = false;
          detail.say(String((err && err.message) || err), true);
        });
      });
      actions.appendChild(save);
    } else {
      actions.appendChild(make('span', 'sp-itin-turn-draft',
        'This is an assembly cue; the exact clip is chosen when the segment goes to air.'));
    }
    detail.box.appendChild(actions);

    if (!turn.planned_sfx) {
      var feedback = make('section', 'sp-itin-feedback');
      feedback.appendChild(make('b', 'sp-itin-feedback-title', 'Tell the orchestrator what to fix'));
      var quick = make('div', 'sp-itin-feedback-quick');
      function sendFeedback(action, note, button) {
        Array.prototype.forEach.call(feedback.querySelectorAll('button'), function (one) {
          one.disabled = true;
        });
        api().post('/api/director/segment/' + encodeURIComponent(entry.occurrence) + '/feedback', {
          action: action, kind: String(entry.kind || ''), slot_id: String(entry.slot_id || ''),
          candidate: String(turn.candidate || script.candidate || ''),
          index: turnCandidateIndex(turn, index),
          candidate_index: turnCandidateIndex(turn, index),
          performance_index: turnPerformanceIndex(turn),
          line: String(turn.text || ''), previous: String(turn.previous || ''),
          topic: String(variant.topic || script.topic || ''), note: String(note || '')
        }).then(function (got) {
          detail.say(String((got && got.say) || 'The note is with the orchestrator.'));
          if (button) button.classList.add('on');
          if (typeof refresh === 'function') setTimeout(refresh, 700);
        }, function (err) {
          Array.prototype.forEach.call(feedback.querySelectorAll('button'), function (one) {
            one.disabled = false;
          });
          detail.say(String((err && err.message) || err), true);
        });
      }
      [['Off topic', 'off_topic'], ['Does not make sense', 'doesnt_make_sense'],
       ['Rewrite', 'rewrite'], ['Refer to previous text', 'refer_to_previous']]
        .forEach(function (pair) {
          var button = make('button', 'sp-itin-feedback-button', pair[0]);
          button.type = 'button';
          button.addEventListener('click', function () { sendFeedback(pair[1], '', button); });
          quick.appendChild(button);
        });
      feedback.appendChild(quick);
      var discuss = make('div', 'sp-itin-feedback-discuss');
      var subject = document.createElement('input');
      subject.placeholder = 'What should they discuss instead?';
      subject.setAttribute('aria-label', 'Replacement subject');
      var discussButton = make('button', 'sp-itin-feedback-button', 'Discuss this instead');
      discussButton.type = 'button';
      discussButton.addEventListener('click', function () {
        var note = String(subject.value || '').trim();
        if (!note) { detail.say('Name the subject you want this line to discuss.', true); return; }
        sendFeedback('discuss_instead', note, discussButton);
      });
      discuss.appendChild(subject); discuss.appendChild(discussButton);
      feedback.appendChild(discuss);
      detail.box.appendChild(feedback);
    }
    return detail;
  }

  function itinConversation(entry, sheet, refresh) {
    var script = (entry && entry.script) || {};
    var bound = script.turns || [];
    var variants = script.draft_variants || [];
    var selectedId = String(script.selected_candidate || '');
    var variant = bound.length ? null
      : (variants.find(function (item) { return String(item.id) === selectedId; })
        || variants[0] || null);
    var turns = itinConversationTurns(entry, variant);
    var performancePlan = scriptPerformances(variant || script);
    var wrap = make('section', 'sp-itin-conversation');
    wrap.addEventListener('click', function (event) { event.stopPropagation(); });
    wrap.addEventListener('keydown', function (event) { event.stopPropagation(); });
    var tools = make('div', 'sp-itin-conversation-tools');
    var views = make('div', 'sp-itin-conversation-views');
    var stage = make('div', 'sp-itin-conversation-body');
    var mode = 'chat';

    function selectVariant(next) {
      variant = next || null;
      turns = itinConversationTurns(entry, variant);
      performancePlan = scriptPerformances(variant || script);
      render();
    }

    function render() {
      stage.replaceChildren();
      stage.setAttribute('data-view', mode);
      if (!turns.length) {
        stage.appendChild(make('p', 'sp-itin-empty',
          'No dialogue is bound to this slot yet. The preparation brief below is what the orchestrator is working from.'));
        if (entry.prompt) stage.appendChild(make('pre', 'sp-itin-setup', String(entry.prompt)));
        return;
      }
      var sections = itinConversationSections(turns);
      var displayTurns = sections.heard.concat(sections.planned);
      var heardCount = sections.heard.length;
      var phase = '';
      var shownPerformance = null;
      displayTurns.forEach(function (turn, index) {
        var nextPhase = turn.aired ? 'heard' : 'planned';
        if (nextPhase !== phase) {
          phase = nextPhase;
          stage.appendChild(make('div', 'sp-itin-conversation-phase',
            phase === 'heard' ? 'Heard / airing'
              : heardCount ? 'Still planned' : 'Prepared for this slot'));
          if (phase === 'planned' && bound.length) {
            var coverage = make('div', 'sp-itin-performance-total',
              performancePlan.rows.length + (performancePlan.rows.length === 1
                ? ' planned performance' : ' planned performances') + ' / '
              + performancePlan.seconds.toFixed(1) + 's planned coverage');
            coverage.dataset.performances = String(performancePlan.rows.length);
            stage.appendChild(coverage);
          }
        }
        var performanceIndex = turnPerformanceIndex(turn);
        if (!turn.aired && !turn.planned_sfx && performanceIndex !== shownPerformance) {
          shownPerformance = performanceIndex;
          var performance = performancePlan.rows.find(function (row) {
            return row.index === performanceIndex;
          }) || {index: performanceIndex, candidate: String(turn.candidate || ''),
            seconds: 0, turns: 0};
          var boundary = make('div', 'sp-itin-performance-boundary', '');
          boundary.dataset.performance = String(performanceIndex);
          boundary.appendChild(make('b', '', 'Planned performance ' + (performanceIndex + 1)));
          boundary.appendChild(make('span', '', [
            performance.candidate,
            performance.turns ? performance.turns + ' turns' : '',
            performance.seconds ? performance.seconds.toFixed(1) + 's' : ''
          ].filter(Boolean).join(' / ')));
          stage.appendChild(boundary);
        }
        var line = make('button', 'sp-itin-message', '');
        line.type = 'button';
        var dialogueId = String(turn.line || '') || ('draft:'
          + String(entry.occurrence || entry.slot_id || entry.kind || 'segment')
          + ':' + String(turn.candidate || script.candidate || 'prepared')
          + ':' + String(turn.prepared_index === undefined ? index : turn.prepared_index));
        line.setAttribute('data-dialogue-id', dialogueId);
        if (turn.line) line.setAttribute('data-line', String(turn.line));
        line.setAttribute('data-kind', String(turn.kind || 'dialogue'));
        if (!turn.aired) {
          line.dataset.performance = String(performanceIndex);
          line.dataset.candidateIndex = String(turnCandidateIndex(turn, index));
        }
        line.classList.toggle('sp-itin-message-even', index % 2 === 0);
        line.appendChild(itinAvatar(turn));
        var bubble = make('span', 'sp-itin-message-bubble');
        bubble.appendChild(make('b', 'sp-itin-message-who',
          String(turn.who || turn.seat || 'speaker')));
        var messageText = make('span', 'sp-itin-message-text', String(turn.text || ''));
        messageText.setAttribute('data-dialogue-text', 'true');
        bubble.appendChild(messageText);
        line.appendChild(bubble);
        line.title = turn.aired ? 'Inspect this aired line and its provenance'
          : (bound.length ? 'Inspect, edit and trace this prepared line'
            : 'Inspect this draft line and its preparation setup');
        line.addEventListener('click', function () {
          itinTurnOpen(entry, turn,
            turn.prepared_index === undefined ? index : turn.prepared_index, refresh);
        });
        stage.appendChild(line);
      });
    }

    [['Chat', 'chat'], ['Transcript', 'transcript'], ['Screenplay', 'screenplay']]
      .forEach(function (pair) {
        var button = make('button', 'sp-itin-conversation-tab', pair[0]);
        button.type = 'button';
        button.addEventListener('click', function () {
          mode = pair[1];
          Array.prototype.forEach.call(views.children, function (one) {
            one.classList.toggle('on', one === button);
          });
          render();
        });
        if (pair[1] === mode) button.classList.add('on');
        views.appendChild(button);
      });
    tools.appendChild(views);
    if (variants.length) {
      var variantsBar = make('div', 'sp-itin-variants');
      variants.forEach(function (item, index) {
        var pick = make('button', 'sp-itin-variant', 'Draft ' + (index + 1));
        pick.type = 'button';
        pick.classList.toggle('on', item === variant);
        pick.title = String((item.topic_review && item.topic_review.ok === false)
          ? 'Topic continuity needs attention' : 'Review this draft');
        pick.addEventListener('click', function () {
          Array.prototype.forEach.call(variantsBar.querySelectorAll('.sp-itin-variant'),
            function (one) { one.classList.toggle('on', one === pick); });
          selectVariant(item);
        });
        variantsBar.appendChild(pick);
      });
      var winner = make('button', 'sp-itin-winner', 'Select winner');
      winner.type = 'button';
      winner.addEventListener('click', function () {
        if (!variant) return;
        winner.disabled = true;
        api().post('/api/director/segment/' + encodeURIComponent(entry.occurrence) + '/winner', {
          kind: String(entry.kind || ''), candidate: String(variant.id || ''),
          candidates: variants.map(function (item) { return String(item.id || ''); })
        }).then(function (got) {
          selectedId = String(variant.id || '');
          winner.textContent = 'Winner selected';
          sheet.say(String((got && got.say) || 'Winner selected.'));
          if (typeof refresh === 'function') setTimeout(refresh, 500);
        }, function (err) {
          winner.disabled = false; sheet.say(String((err && err.message) || err), true);
        });
      });
      variantsBar.appendChild(winner);
      tools.appendChild(variantsBar);
    }
    var prepare = make('button', 'sp-itin-prepare',
      turns.length ? 'Prepare another' : 'Prepare now');
    prepare.type = 'button';
    prepare.disabled = String(entry.kind || '') === 'record';
    prepare.addEventListener('click', function () {
      prepare.disabled = true;
      api().post('/api/pantry/commission', {
        kind: String(entry.kind || ''), count: 1
      }).then(function (got) {
        prepare.textContent = 'Queued ' + String((got && got.label) || entry.kind || 'segment');
        sheet.say('The orchestrator is preparing this road now.');
        setTimeout(function () {
          if (typeof refresh === 'function') refresh();
        }, 2200);
      }, function (err) {
        prepare.disabled = false;
        sheet.say(String((err && err.message) || err), true);
      });
    });
    tools.appendChild(prepare);
    if (bound.length && entry.occurrence) {
      var approved = !!(entry.review && entry.review.approved);
      var approve = make('button', 'sp-itin-prepare sp-itin-approve',
        approved ? 'Script approved' : 'Approve script');
      approve.type = 'button';
      approve.disabled = approved;
      approve.addEventListener('click', function () {
        approve.disabled = true;
        api().post('/api/director/segment/'
          + encodeURIComponent(entry.occurrence) + '/approve',
          {who: 'operator'}).then(function (got) {
          approve.textContent = 'Script approved';
          sheet.say(String((got && got.say) || 'Script approved.'));
          loadPlan(true);
          if (typeof refresh === 'function') setTimeout(refresh, 500);
        }, function (err) {
          approve.disabled = false;
          sheet.say(String((err && err.message) || err), true);
        });
      });
      tools.appendChild(approve);
    }
    wrap.appendChild(tools);
    wrap.appendChild(stage);
    render();
    return wrap;
  }

  /* ---- #1301: the scheduled conversation-flow editor ---------------- */

  /* A slot's flow is deliberately a small JSON shape. It is persisted with
     the scheduler and compiled into the writing-room clause on the server;
     this page only gives the operator a direct, tactile way to arrange it. */
  var FLOW_TYPES = [
    ['scripted_line', 'Scripted line', 12],
    ['news_mention', 'News mention', 48],
    ['speakerbox_quote', 'Speakerbox quote', 30],
    ['random_topic', 'Random topic', 52],
    ['caller', 'Caller', 82],
    ['manager_message', 'Manager message', 42],
    ['sfx', 'SFX', 6],
    ['ad_drop', 'Ad drop', 32],
    ['painting_ad', 'Painting ad', 58],
    ['product', 'Product pitch', 48]
  ];

  function flowType(type) {
    return FLOW_TYPES.find(function (row) { return row[0] === String(type || ''); })
      || FLOW_TYPES[2];
  }

  function flowClip(raw) {
    raw = raw && typeof raw === 'object' ? raw : {};
    var id = String(raw.id || '').trim().toLowerCase();
    if (!/^[0-9a-f]{16}$/.test(id)) return {};
    var seconds = Number(raw.seconds);
    return {id: id, name: String(raw.name || 'Scheduled clip').slice(0, 120),
      seconds: isFinite(seconds) ? Math.max(0, Math.min(120, seconds)) : 0,
      video: !!raw.video};
  }

  function flowNode(raw, index) {
    var spec = flowType(raw && raw.type);
    var seconds = Number(raw && raw.seconds);
    if (!isFinite(seconds) || seconds <= 0) seconds = spec[2];
    var source = raw && raw.line && typeof raw.line === 'object' ? raw.line : {};
    return {id: String((raw && raw.id) || ('flow-' + Date.now() + '-' + index + '-' + Math.random().toString(36).slice(2, 7))),
      type: spec[0], seconds: Math.max(2, Math.min(900, Math.round(seconds * 10) / 10)),
      detail: String((raw && raw.detail) || '').slice(0, 400),
      after: String((raw && raw.after) || '').slice(0, 96),
      line: spec[0] === 'scripted_line' ? {
        speaker: String(source.speaker || 'Host').slice(0, 60),
        text: String(source.text || '').slice(0, 900),
        source: String(source.source || 'operator').slice(0, 80)
      } : {},
      clip: spec[0] === 'sfx' ? flowClip(raw && raw.clip) : {}};
  }

  function flowIconButton(cls, icon, label) {
    var button = make('button', cls, '');
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.innerHTML = folderIcon(icon, label);
    if (!button.innerHTML) button.textContent = label;
    return button;
  }

  function flowDictation(field, sheet) {
    var button = flowIconButton('sp-flow-mic', 'c:microphone', 'Dictate into this field');
    var timer = 0;
    var pressTimer = 0;
    var holding = false;
    var ignoreClick = false;
    function finish() {
      if (timer) clearTimeout(timer);
      timer = 0;
      button.classList.remove('on');
    }
    function start() {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') {
        sheet.say('No microphone is available on this surface.', true);
        return;
      }
      button.classList.add('on');
      try {
        dot.captureNext(function (words) {
          var text = String(words || '').trim();
          if (text) {
            field.value = String(field.value || '')
              + (String(field.value || '').trim() ? ' ' : '') + text;
            field.dispatchEvent(new Event('input', {bubbles: true}));
          }
          finish();
        });
        timer = setTimeout(finish, 30000);
      } catch (err) {
        finish();
        sheet.say('The microphone could not start.', true);
      }
    }
    button.addEventListener('click', function () {
      if (ignoreClick) { ignoreClick = false; return; }
      if (button.classList.contains('on') && root.PineTalkDot
          && typeof root.PineTalkDot.finish === 'function') {
        root.PineTalkDot.finish(); finish(); return;
      }
      start();
    });
    button.addEventListener('pointerdown', function () {
      holding = false;
      pressTimer = setTimeout(function () { holding = true; start(); }, 220);
    });
    button.addEventListener('pointerup', function () {
      if (pressTimer) clearTimeout(pressTimer);
      pressTimer = 0;
      if (!holding) return;
      ignoreClick = true;
      if (root.PineTalkDot && typeof root.PineTalkDot.finish === 'function') root.PineTalkDot.finish();
      finish();
    });
    button.addEventListener('pointercancel', function () {
      if (pressTimer) clearTimeout(pressTimer);
      pressTimer = 0; finish();
    });
    return button;
  }

  function flowField(label, field, sheet, cls, dictate) {
    var wrap = make('label', 'sp-flow-field' + (cls ? ' ' + cls : ''));
    wrap.appendChild(make('span', 'sp-flow-field-label', label));
    var inner = make('div', 'sp-flow-field-inner');
    inner.appendChild(field);
    if (dictate !== false) inner.appendChild(flowDictation(field, sheet));
    else wrap.classList.add('sp-flow-no-mic');
    wrap.appendChild(inner);
    return wrap;
  }

  function itineraryFlowOpen(entry, parentSheet, refresh) {
    var name = String(entry.label || entry.kind || 'Scheduled segment');
    var sheet = sheetShell('spSegmentFlow', 'sp-flowedit', 'Shape: ' + name);
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-spSegmentFlow', root.PineDuck.REPORT, sheet.back);
    }
    var flow = (Array.isArray(entry.flow) ? entry.flow : []).map(flowNode);
    var storyline = [];
    var selected = flow.length ? flow[0].id : '';
    var dragId = '';
    var preset = String(entry.schedule_preset || '');
    var returnTarget = parentSheet && parentSheet.returnTarget
      ? parentSheet.returnTarget : null;
    var lineOrigin = entry && entry.flow_origin && typeof entry.flow_origin === 'object'
      ? entry.flow_origin : null;
    storyline = orchestratorStoryline();
    if (lineOrigin) {
      var originNode = storyline.find(function (node) {
        return String(node.lineId || '') === String(lineOrigin.id || '');
      });
      if (originNode) selected = originNode.id;
    }
    if (!selected && storyline.length) selected = storyline[0].id;

    var form = make('section', 'sp-flow-editor');
    if (lineOrigin) {
      var origin = make('section', 'sp-flow-origin');
      origin.appendChild(make('b', '', 'Selected scripted line'));
      origin.appendChild(make('span', '', String(lineOrigin.text || 'This line belongs to this scheduled segment.')));
      origin.appendChild(make('i', '', String(lineOrigin.id || '')));
      form.appendChild(origin);
    }
    var provenance = make('section', 'sp-flow-provenance');
    provenance.appendChild(make('b', 'sp-flow-provenance-title', 'How this segment is assembled'));
    var route = make('div', 'sp-flow-provenance-route');
    route.appendChild(make('b', '', String(entry.kind || 'segment')));
    route.appendChild(make('span', '', 'slot ' + String(entry.slot_id || 'not pinned')));
    route.appendChild(make('span', '', 'prompt ' + String(entry.prompt_id || 'active variant')));
    provenance.appendChild(route);
    var systemPrompt = document.createElement('textarea');
    systemPrompt.rows = 6; systemPrompt.maxLength = 4000;
    systemPrompt.placeholder = 'The system prompt that guides this road...';
    systemPrompt.value = String(entry.prompt || '');
    systemPrompt.setAttribute('aria-label', 'Active system prompt');
    provenance.appendChild(flowField('Active system prompt', systemPrompt, sheet));
    var sourceNotes = document.createElement('textarea');
    sourceNotes.rows = 3; sourceNotes.maxLength = 400;
    sourceNotes.placeholder = 'Station inputs, constraints, or preparation notes...';
    sourceNotes.value = String(entry.notes || '');
    sourceNotes.setAttribute('aria-label', 'Segment input notes');
    provenance.appendChild(flowField('Station inputs and preparation', sourceNotes, sheet));
    var savePrompt = flowIconButton('sp-flow-prompt-save', 'c:save',
      'Save the active system prompt for this segment kind');
    savePrompt.appendChild(make('span', '', 'Save system prompt'));
    provenance.appendChild(savePrompt);
    form.appendChild(provenance);
    var basics = make('div', 'sp-flow-basics');
    var label = document.createElement('input');
    label.type = 'text'; label.maxLength = 80; label.value = name;
    label.setAttribute('aria-label', 'Segment name');
    var minutes = document.createElement('input');
    minutes.type = 'number'; minutes.min = '.25'; minutes.max = '600'; minutes.step = '.25';
    minutes.value = String(Math.max(.25, Number(entry.minutes) || 3));
    minutes.setAttribute('aria-label', 'Segment duration in minutes');
    basics.appendChild(flowField('Segment name', label, sheet));
    basics.appendChild(flowField('Minutes', minutes, sheet, 'sp-flow-minutes', false));
    form.appendChild(basics);

    var savedGraphs = [];
    var selectedGraph = '';
    var library = make('section', 'sp-flow-library');
    library.appendChild(make('b', 'sp-flow-library-title', 'Saved segment graphs'));
    var libraryPick = document.createElement('select');
    libraryPick.setAttribute('aria-label', 'Saved segment graph');
    library.appendChild(flowField('Open a saved graph', libraryPick, sheet,
      'sp-flow-library-pick', false));
    var cycle = make('div', 'sp-flow-library-cycle');
    var previousGraph = flowIconButton('sp-flow-library-arrow', 'c:caret--left',
      'Previous saved graph');
    var nextGraph = flowIconButton('sp-flow-library-arrow', 'c:caret--right',
      'Next saved graph');
    cycle.appendChild(previousGraph); cycle.appendChild(nextGraph);
    library.appendChild(cycle);
    var graphName = document.createElement('input');
    graphName.type = 'text'; graphName.maxLength = 80;
    graphName.placeholder = 'Name this reusable graph'; graphName.value = name + ' graph';
    graphName.setAttribute('aria-label', 'Saved graph name');
    library.appendChild(flowField('Save graph as', graphName, sheet,
      'sp-flow-library-name'));
    var saveGraph = flowIconButton('sp-flow-library-save', 'c:save', 'Save this graph');
    var saveGraphWords = make('span', '', 'Save graph');
    saveGraph.appendChild(saveGraphWords);
    var copyGraph = flowIconButton('sp-flow-library-copy', 'c:copy--to-clipboard',
      'Save this graph as a new reusable graph');
    copyGraph.appendChild(make('span', '', 'Save copy'));
    library.appendChild(saveGraph); library.appendChild(copyGraph);
    form.appendChild(library);

    var direction = document.createElement('textarea');
    direction.className = 'sp-flow-direction';
    direction.rows = 3;
    direction.placeholder = 'Additional system direction for this segment...';
    direction.value = String(entry.flow_prompt || '');
    direction.setAttribute('aria-label', 'Additional system direction for this segment');
    form.appendChild(flowField('System direction for this segment', direction, sheet));

    var timing = make('section', 'sp-flow-timing');
    var timingHead = make('div', 'sp-flow-timing-head');
    var timingLabel = make('b', '', 'Conversation timing');
    var timingRead = make('span', 'sp-flow-timing-read', '');
    timingHead.appendChild(timingLabel); timingHead.appendChild(timingRead);
    var timingRail = make('div', 'sp-flow-timing-rail');
    var timingFill = make('div', 'sp-flow-timing-fill');
    timingRail.appendChild(timingFill);
    timing.appendChild(timingHead); timing.appendChild(timingRail);
    form.appendChild(timing);

    var utility = make('div', 'sp-flow-utility');
    var suggest = flowIconButton('sp-flow-suggest', 'c:magic-wand--filled', 'Let the orchestrator suggest a timed flow');
    var suggestWords = make('span', '', 'Orchestrator suggests');
    suggest.appendChild(suggestWords);
    var speakerbox = flowIconButton('sp-flow-speakerbox', 'c:search', 'Find Speakerbox passages for this segment');
    speakerbox.appendChild(make('span', '', 'Speakerbox suggestions'));
    utility.appendChild(suggest); utility.appendChild(speakerbox);
    form.appendChild(utility);

    var speakResults = make('div', 'sp-flow-speakerbox-results');
    speakResults.hidden = true;
    form.appendChild(speakResults);

    var work = make('div', 'sp-flow-work');
    var palette = make('aside', 'sp-flow-palette');
    palette.appendChild(make('b', 'sp-flow-section-title', 'Interject a node'));
    FLOW_TYPES.forEach(function (spec) {
      var button = make('button', 'sp-flow-palette-node', spec[1]);
      button.type = 'button'; button.draggable = true;
      button.dataset.type = spec[0];
      button.title = 'Drag ' + spec[1] + ' into the conversation flow';
      button.addEventListener('dragstart', function (event) {
        dragId = ''; event.dataTransfer.setData('text/pine-flow-type', spec[0]);
        event.dataTransfer.effectAllowed = 'copy';
      });
      button.addEventListener('click', function () { add(spec[0]); });
      palette.appendChild(button);
    });
    var graph = make('section', 'sp-flow-graph');
    graph.setAttribute('aria-label', 'Conversation flow graph');
    var side = make('aside', 'sp-flow-sidebar');
    work.appendChild(palette); work.appendChild(graph); work.appendChild(side);
    form.appendChild(work);

    var saveBar = make('div', 'sp-flow-savebar');
    if (returnTarget) {
      var backToOrder = flowIconButton('sp-flow-return', 'c:caret--left',
        'Return to the running order');
      backToOrder.addEventListener('click', function () {
        sheet.close(); itineraryOpen(returnTarget);
      });
      saveBar.appendChild(backToOrder);
    }
    var applyKind = make('button', 'sp-flow-apply-kind', 'Apply to every ' + String(entry.kind || 'segment'));
    applyKind.type = 'button';
    applyKind.title = 'Use this flow for every matching segment in this saved schedule';
    var save = make('button', 'sp-flow-save', 'Save segment flow');
    save.type = 'button';
    saveBar.appendChild(applyKind); saveBar.appendChild(save);
    form.appendChild(saveBar);
    sheet.box.appendChild(form);

    function storySeconds(turn) {
      var explicit = Number(turn && turn.seconds);
      if (isFinite(explicit) && explicit > 0) return Math.max(2, Math.min(120, explicit));
      if (turn && turn.planned_sfx) return 6;
      var words = String((turn && turn.text) || '').trim().split(/\s+/).filter(Boolean).length;
      return Math.max(2, Math.min(120, Math.round((words || 6) / 2.45)));
    }
    function storyId(turn, index) {
      var key = String((turn && (turn.line || turn.line_id || turn.id || turn.candidate)) || ('turn-' + index));
      return 'orchestrator-' + key.replace(/[^a-z0-9_-]+/ig, '-').slice(0, 64) + '-' + index;
    }
    function orchestratorStoryline() {
      return itinConversationTurns(entry).map(function (turn, index) {
        var sfx = !!turn.planned_sfx || String(turn.kind || '').toLowerCase() === 'sfx';
        var who = String(turn.who || turn.name || turn.seat || (sfx ? 'The SFX Guy' : 'Host'));
        return {
          id: storyId(turn, index), type: sfx ? 'sfx' : 'scripted_line',
          seconds: storySeconds(turn), detail: String(turn.text || '').slice(0, 400),
          line: {speaker: who, text: String(turn.text || '').slice(0, 900),
            source: turn.aired ? 'Aired script' : (turn.draft ? 'Orchestrator draft' : 'Orchestrator script')},
          clip: flowClip(turn.clip), locked: true, turn: turn,
          lineId: String(turn.line || turn.line_id || ''), planned: sfx
        };
      });
    }
    function graphNodes() {
      var out = [], seen = {};
      function append(node) {
        if (!node || seen[node.id]) return;
        seen[node.id] = true; out.push(node);
        flow.filter(function (item) { return String(item.after || '') === String(node.id); })
          .forEach(append);
      }
      flow.filter(function (item) { return String(item.after || '') === '__start'; }).forEach(append);
      storyline.forEach(append);
      flow.filter(function (item) { return !String(item.after || ''); }).forEach(append);
      flow.forEach(append); // stale anchors still remain visible and editable.
      return out;
    }
    function total() { return graphNodes().reduce(function (sum, node) { return sum + (Number(node.seconds) || 0); }, 0); }
    function target() { return Math.max(15, (Number(minutes.value) || 3) * 60); }
    function updateTiming() {
      var used = total(), allowed = target(), ratio = Math.min(1, used / allowed);
      timingFill.style.width = (ratio * 100).toFixed(1) + '%';
      timing.classList.toggle('over', used > allowed);
      timingRead.textContent = Math.round(used) + 's of ' + Math.round(allowed) + 's'
        + (used > allowed ? ' - over by ' + Math.round(used - allowed) + 's' : ' - ' + Math.round(allowed - used) + 's open');
    }
    function add(type, detail, after) {
      var spec = flowType(type);
      var node = flowNode({type: spec[0], seconds: spec[2], detail: detail || '',
        after: after || selected || '__start'}, flow.length);
      flow.push(node); selected = node.id; render();
      if (node.type === 'sfx') primeSfxNodes();
    }
    function selectedNode() {
      return graphNodes().find(function (node) { return node.id === selected; }) || null;
    }
    function reorder(from, after) {
      var moved = flow.find(function (node) { return node.id === from; });
      if (!moved || moved.id === after) return;
      moved.after = String(after || '__start'); selected = moved.id; render();
    }
    function sfxClipWords(clip) {
      clip = flowClip(clip);
      if (!clip.id) return '';
      return (clip.video ? 'MP4' : 'audio') + ' - ' + clip.name
        + (clip.seconds ? ' (' + clip.seconds.toFixed(1) + 's)' : '');
    }
    var sfxPlanBusy = false;
    function primeSfxNodes(force) {
      if (sfxPlanBusy || !api() || !api().post) return;
      var nodes = graphNodes();
      var node = nodes.find(function (item) {
        return item.type === 'sfx' && !item.sfxPlanning
          && (force ? item.id === force : (!flowClip(item.clip).id && !item.sfxTried));
      });
      if (!node) return;
      sfxPlanBusy = true; node.sfxPlanning = true;
      renderGraph(); renderSide();
      var excluded = nodes.filter(function (item) { return item.id !== node.id; })
        .map(function (item) { return flowClip(item.clip).id; }).filter(Boolean);
      api().post('/api/schedule/flow/sfx/plan', {
        label: label.value, notes: sourceNotes.value, prompt: direction.value,
        detail: node.detail, seconds: node.seconds, excluded: excluded
      }).then(function (got) {
        node.clip = flowClip(got && got.clip);
        node.sfxTried = true;
        if (node.id === selected) render(); else renderGraph();
      }, function () {
        node.sfxTried = true;
        if (node.id === selected) render(); else renderGraph();
      })['finally'](function () {
        node.sfxPlanning = false; sfxPlanBusy = false;
        if (node.id === selected) render(); else renderGraph();
        if (!force) primeSfxNodes();
      });
    }
    function renderGraph() {
      graph.replaceChildren();
      var nodes = graphNodes();
      graph.classList.toggle('empty', !nodes.length);
      var storyHead = make('div', 'sp-flow-storyline');
      storyHead.appendChild(make('b', '', 'Orchestrator storyline'));
      storyHead.appendChild(make('span', '', storyline.length
        ? storyline.length + ' scripted events from the current segment'
        : 'No generated lines are banked for this segment yet'));
      graph.appendChild(storyHead);
      if (!nodes.length) {
        graph.appendChild(make('div', 'sp-flow-empty', 'Drag a node here, or ask the orchestrator to lay one out.'));
      }
      nodes.forEach(function (node, index) {
        var spec = flowType(node.type);
        var card = make('article', 'sp-flow-node' + (node.type === 'sfx' ? ' is-sfx' : '')
          + (node.type === 'scripted_line' ? ' is-scripted' : '')
          + (node.locked ? ' locked' : '')
          + (node.id === selected ? ' selected' : ''));
        card.draggable = !node.locked; card.dataset.node = node.id;
        card.title = node.locked ? 'Generated by the orchestrator; select to review it'
          : 'Drag to place this node after another part of the storyline';
        card.appendChild(make('span', 'sp-flow-node-order', String(index + 1)));
        var words = make('div', 'sp-flow-node-words');
        words.appendChild(make('b', '', spec[1]));
        if (node.type === 'scripted_line') {
          words.appendChild(make('span', 'sp-flow-node-speaker',
            String((node.line || {}).speaker || 'Host') + ' - '
            + String((node.line || {}).source || 'operator')));
          words.appendChild(make('span', 'sp-flow-node-script',
            String((node.line || {}).text || 'Write the line in the sidebar.')));
        } else {
          words.appendChild(make('span', '', Math.round(node.seconds) + ' seconds'));
        }
        if (node.type === 'sfx') {
          var clipWords = sfxClipWords(node.clip);
          words.appendChild(make('span', 'sp-flow-node-clip', clipWords
            || (node.sfxPlanning ? 'Selecting a clip...' : (node.planned
              ? 'SFX scheduled by the orchestrator' : 'No clip selected'))));
        }
        card.appendChild(words);
        if (node.locked) {
          card.appendChild(make('span', 'sp-flow-node-lock', 'Locked'));
        } else {
          var drop = flowIconButton('sp-flow-node-delete', 'c:trash-can', 'Remove this node');
          drop.addEventListener('click', function (event) {
            event.stopPropagation(); flow = flow.filter(function (item) { return item.id !== node.id; });
            selected = (graphNodes()[Math.max(0, index - 1)] || {}).id || ''; render();
          });
          card.appendChild(drop);
        }
        card.addEventListener('click', function () { selected = node.id; render(); });
        if (!node.locked) {
          card.addEventListener('dragstart', function (event) {
            dragId = node.id; event.dataTransfer.setData('text/pine-flow-node', node.id);
            event.dataTransfer.effectAllowed = 'move'; card.classList.add('dragging');
          });
          card.addEventListener('dragend', function () { card.classList.remove('dragging'); });
        }
        card.addEventListener('dragover', function (event) { event.preventDefault(); card.classList.add('over'); });
        card.addEventListener('dragleave', function () { card.classList.remove('over'); });
        card.addEventListener('drop', function (event) {
          event.preventDefault(); card.classList.remove('over');
          var type = event.dataTransfer.getData('text/pine-flow-type');
          var source = event.dataTransfer.getData('text/pine-flow-node') || dragId;
          if (type) {
            add(type, '', node.id); return;
          }
          if (source) reorder(source, node.id);
        });
        graph.appendChild(card);
      });
      graph.ondragover = function (event) { event.preventDefault(); graph.classList.add('drop-ready'); };
      graph.ondragleave = function () { graph.classList.remove('drop-ready'); };
      graph.ondrop = function (event) {
        event.preventDefault(); graph.classList.remove('drop-ready');
        var type = event.dataTransfer.getData('text/pine-flow-type');
        var last = graphNodes().slice(-1)[0];
        if (type) add(type, '', last && last.id);
        else {
          var source = event.dataTransfer.getData('text/pine-flow-node') || dragId;
          if (source) reorder(source, last && last.id);
        }
      };
    }
    function renderSide() {
      side.replaceChildren();
      var node = selectedNode();
      if (!node) {
        side.appendChild(make('div', 'sp-flow-empty', 'Select a beat to adjust it.'));
        return;
      }
      side.appendChild(make('b', 'sp-flow-section-title', node.locked
        ? 'Orchestrator scripted event' : 'Selected node'));
      if (node.locked) {
        var generated = make('section', 'sp-flow-script-source');
        generated.appendChild(make('b', '', node.type === 'sfx'
          ? 'Scheduled SFX event' : String((node.line || {}).speaker || 'Host')));
        generated.appendChild(make('span', '', node.type === 'sfx'
          ? (sfxClipWords(node.clip) || 'The SFX Guy has this event scheduled in the broadcast.')
          : String((node.line || {}).text || 'No text is banked for this event.')));
        generated.appendChild(make('i', '', node.type === 'sfx'
          ? 'This SFX event is placed by the orchestrator.'
          : String((node.line || {}).source || 'Orchestrator script') + ' - ' + Math.round(node.seconds) + ' seconds'));
        side.appendChild(generated);
        side.appendChild(make('div', 'sp-flow-empty',
          'Generated lines stay intact here. Select a line, then add or drag a node to interject after it.'));
        return;
      }
      var type = document.createElement('select');
      FLOW_TYPES.forEach(function (spec) {
        var option = make('option', '', spec[1]); option.value = spec[0];
        option.selected = spec[0] === node.type; type.appendChild(option);
      });
      type.setAttribute('aria-label', 'Beat type');
      type.addEventListener('change', function () {
        node.type = type.value;
        node.clip = {};
        node.line = node.type === 'scripted_line'
          ? {speaker: 'Host', text: '', source: 'operator'} : {};
        node.sfxTried = false;
        render();
        if (node.type === 'sfx') primeSfxNodes();
      });
      var seconds = document.createElement('input');
      seconds.type = 'number'; seconds.min = '2'; seconds.max = '900'; seconds.step = '1'; seconds.value = String(node.seconds);
      seconds.setAttribute('aria-label', 'Beat duration in seconds');
      seconds.addEventListener('input', function () {
        node.seconds = Math.max(2, Math.min(900, Number(seconds.value) || flowType(node.type)[2])); updateTiming(); renderGraph();
      });
      var detail = document.createElement('textarea');
      detail.rows = 4; detail.maxLength = 400; detail.placeholder = 'What should this beat draw on?'; detail.value = node.detail;
      detail.setAttribute('aria-label', 'Beat detail');
      detail.addEventListener('input', function () { node.detail = detail.value.slice(0, 400); });
      side.appendChild(flowField('Type', type, sheet, '', false));
      side.appendChild(flowField('Seconds', seconds, sheet, '', false));
      side.appendChild(flowField(node.type === 'scripted_line'
        ? 'Direction around this line' : 'Detail', detail, sheet));
      if (node.type === 'scripted_line') {
        node.line = node.line || {speaker: 'Host', text: '', source: 'operator'};
        var speaker = document.createElement('input');
        speaker.type = 'text'; speaker.maxLength = 60;
        speaker.value = String(node.line.speaker || 'Host');
        speaker.setAttribute('aria-label', 'Scripted line speaker');
        speaker.addEventListener('input', function () { node.line.speaker = speaker.value.slice(0, 60) || 'Host'; renderGraph(); });
        var script = document.createElement('textarea');
        script.rows = 6; script.maxLength = 900;
        script.placeholder = 'What should this speaker say on air?';
        script.value = String(node.line.text || '');
        script.setAttribute('aria-label', 'Scripted line text');
        script.addEventListener('input', function () { node.line.text = script.value.slice(0, 900); renderGraph(); });
        side.appendChild(flowField('Speaker', speaker, sheet));
        side.appendChild(flowField('Script', script, sheet));
      }
      if (node.type === 'sfx') {
        var selectedClip = flowClip(node.clip);
        var clip = make('section', 'sp-flow-sfx-clip');
        clip.appendChild(make('b', '', 'Scheduled clip'));
        clip.appendChild(make('span', '', sfxClipWords(selectedClip)
          || (node.sfxPlanning ? 'Selecting from the indexed clip library...' : 'No eligible clip selected.')));
        var reseat = flowIconButton('sp-flow-sfx-reseat', 'c:renew',
          'Choose another scheduled SFX clip');
        reseat.addEventListener('click', function () {
          node.clip = {}; node.sfxTried = false; primeSfxNodes(node.id);
        });
        clip.appendChild(reseat);
        side.appendChild(clip);
      }
      var remove = flowIconButton('sp-flow-sidebar-delete', 'c:trash-can', 'Remove selected beat');
      remove.appendChild(make('span', '', 'Remove beat'));
      remove.addEventListener('click', function () {
        flow = flow.filter(function (item) { return item.id !== node.id; }); selected = (graphNodes()[0] || {}).id || ''; render();
      });
      side.appendChild(remove);
    }
    function render() { updateTiming(); renderGraph(); renderSide(); }

    var systemPromptDirty = false;
    systemPrompt.addEventListener('input', function () { systemPromptDirty = true; });
    function promptSlot(book) {
      var blob = (book && book[String(entry.kind || '')]) || {};
      var variants = Array.isArray(blob.variants) ? blob.variants.slice() : [];
      if (!variants.length) variants.push({id: '', name: 'Station default', text: ''});
      var index = variants.findIndex(function (row) {
        return String(row.id || '') === String(entry.prompt_id || '');
      });
      if (index < 0) index = Math.max(0, Math.min(variants.length - 1, Number(blob.active) || 0));
      return {variants: variants, index: index};
    }
    function loadSystemPrompt() {
      if (!api() || !api().get || !String(entry.kind || '')) return;
      api().get('/api/schedule/prompts').then(function (book) {
        var picked = promptSlot(book);
        var text = String((picked.variants[picked.index] || {}).text || '');
        if (!systemPromptDirty && text) systemPrompt.value = text;
      }, function () { /* The director supplied the prompt already. */ });
    }
    function saveSystemPrompt() {
      if (!api() || !api().get || !api().post || !String(entry.kind || '')) {
        sheet.say('This segment has no writable prompt route.', true); return;
      }
      var text = String(systemPrompt.value || '').trim();
      if (!text) { sheet.say('The system prompt is empty.', true); return; }
      savePrompt.disabled = true;
      api().get('/api/schedule/prompts').then(function (book) {
        var picked = promptSlot(book);
        var row = Object.assign({}, picked.variants[picked.index] || {});
        row.id = String(row.id || entry.prompt_id || (String(entry.kind) + '-operator'));
        row.name = String(row.name || entry.label || entry.kind || 'Station prompt').slice(0, 80);
        row.text = text;
        picked.variants[picked.index] = row;
        return api().post('/api/schedule/prompts', {
          [String(entry.kind || '')]: {active: picked.index, variants: picked.variants}
        });
      }).then(function () {
        systemPromptDirty = false;
        entry.prompt = text; entry.prompt_id = String(entry.prompt_id || '');
        sheet.say('Saved the active system prompt for future ' + String(entry.kind || 'segment') + ' segments.');
      }, function (err) { sheet.say(String((err && err.message) || err), true); })
        ['finally'](function () { savePrompt.disabled = false; });
    }
    savePrompt.addEventListener('click', saveSystemPrompt);

    function activeSavedGraph() {
      return savedGraphs.find(function (graph) { return graph.id === selectedGraph; }) || null;
    }
    function refreshLibraryControls() {
      var graph = activeSavedGraph();
      previousGraph.disabled = savedGraphs.length < 2;
      nextGraph.disabled = savedGraphs.length < 2;
      saveGraphWords.textContent = graph ? 'Update graph' : 'Save graph';
      saveGraph.title = graph ? 'Update the selected saved graph' : 'Save this graph for reuse';
    }
    function useSavedGraph(graph) {
      if (!graph) return;
      selectedGraph = String(graph.id || '');
      libraryPick.value = selectedGraph;
      flow = (Array.isArray(graph.flow) ? graph.flow : []).map(flowNode);
      selected = flow.length ? flow[0].id : '';
      direction.value = String(graph.flow_prompt || '');
      minutes.value = String(Math.max(.25, Number(graph.minutes) || 3));
      graphName.value = String(graph.name || 'Untitled segment graph');
      refreshLibraryControls(); render(); primeSfxNodes();
      sheet.say('Loaded saved graph: ' + graphName.value + '.');
    }
    function loadSavedGraphs(prefer) {
      if (!api() || !api().get) return;
      api().get('/api/schedule/flow/library').then(function (got) {
        savedGraphs = Array.isArray(got && got.graphs) ? got.graphs : [];
        var wanted = String(prefer || selectedGraph || '');
        if (!savedGraphs.some(function (graph) { return String(graph.id || '') === wanted; })) wanted = '';
        selectedGraph = wanted;
        libraryPick.replaceChildren();
        var current = make('option', '', 'Current segment graph');
        current.value = ''; libraryPick.appendChild(current);
        savedGraphs.forEach(function (graph) {
          var option = make('option', '', String(graph.name || 'Untitled segment graph'));
          option.value = String(graph.id || ''); libraryPick.appendChild(option);
        });
        libraryPick.value = selectedGraph;
        refreshLibraryControls();
      }, function (err) { sheet.say(String((err && err.message) || err), true); });
    }
    function cycleSavedGraph(step) {
      if (!savedGraphs.length) return;
      var index = savedGraphs.findIndex(function (graph) { return graph.id === selectedGraph; });
      index = (index + step + savedGraphs.length) % savedGraphs.length;
      useSavedGraph(savedGraphs[index]);
    }
    function saveSavedGraph(asCopy) {
      saveGraph.disabled = true; copyGraph.disabled = true;
      var graph = activeSavedGraph();
      api().post('/api/schedule/flow/library', {
        id: asCopy ? '' : String((graph && graph.id) || ''),
        name: String(graphName.value || label.value || 'Untitled segment graph'),
        kind: String(entry.kind || ''), minutes: Number(minutes.value) || 3,
        flow_prompt: direction.value, flow: flow
      }).then(function (got) {
        var saved = got && got.graph;
        selectedGraph = String((saved && saved.id) || '');
        graphName.value = String((saved && saved.name) || graphName.value || 'Untitled segment graph');
        sheet.say(String((got && got.say) || 'Saved reusable segment graph.'));
        loadSavedGraphs(selectedGraph);
      }, function (err) { sheet.say(String((err && err.message) || err), true); })
        ['finally'](function () { saveGraph.disabled = false; copyGraph.disabled = false; });
    }

    libraryPick.addEventListener('change', function () {
      var picked = savedGraphs.find(function (graph) { return graph.id === libraryPick.value; });
      if (!picked) {
        selectedGraph = ''; refreshLibraryControls(); return;
      }
      useSavedGraph(picked);
    });
    previousGraph.addEventListener('click', function () { cycleSavedGraph(-1); });
    nextGraph.addEventListener('click', function () { cycleSavedGraph(1); });
    saveGraph.addEventListener('click', function () { saveSavedGraph(false); });
    copyGraph.addEventListener('click', function () { saveSavedGraph(true); });

    function suggestFlow() {
      suggest.disabled = true; suggestWords.textContent = 'Planning...';
      api().post('/api/schedule/flow/suggest', {kind: String(entry.kind || 'banter'),
        label: label.value, minutes: Number(minutes.value) || 3, notes: String(sourceNotes.value || '')})
        .then(function (got) {
          flow = ((got && got.nodes) || []).map(flowNode);
          selected = flow.length ? flow[0].id : '';
          render(); primeSfxNodes();
          sheet.say(String((got && got.say) || 'The orchestrator proposed a flow.'));
        }, function (err) { sheet.say(String((err && err.message) || err), true); })
        ['finally'](function () { suggest.disabled = false; suggestWords.textContent = 'Orchestrator suggests'; });
    }
    suggest.addEventListener('click', suggestFlow);
    speakerbox.addEventListener('click', function () {
      speakerbox.disabled = true; speakResults.hidden = false;
      speakResults.textContent = 'Searching Speakerbox...';
      var query = [label.value, entry.notes, direction.value, entry.prompt].filter(Boolean).join(' ').slice(0, 700);
      api().get('/api/speakbox/search?k=5&q=' + encodeURIComponent(query || String(entry.kind || 'banter')))
        .then(function (got) {
          var hits = (got && got.hits) || [];
          speakResults.replaceChildren();
          if (!hits.length) { speakResults.appendChild(make('div', 'sp-flow-empty', 'No matching Speakerbox passages were returned.')); return; }
          hits.forEach(function (hit) {
            var line = make('button', 'sp-flow-speak-hit', ''); line.type = 'button';
            var source = String(hit.name || hit.doc || hit.file || 'Speakerbox passage');
            var passage = String(hit.text || hit.passage || hit.quote || hit.preview || '').replace(/\s+/g, ' ').slice(0, 260);
            line.appendChild(make('b', '', source)); line.appendChild(make('span', '', passage || 'Add this passage to the flow'));
            line.addEventListener('click', function () { add('speakerbox_quote', source + (passage ? ': ' + passage : '')); sheet.say('Speakerbox quote added to the flow.'); });
            speakResults.appendChild(line);
          });
        }, function (err) { speakResults.textContent = String((err && err.message) || err); })
        ['finally'](function () { speakerbox.disabled = false; });
    });
    minutes.addEventListener('input', updateTiming);
    function saveFlow(allOfKind) {
      save.disabled = true; applyKind.disabled = true;
      api().post('/api/schedule/flow/slot', {preset: preset, slot_id: String(entry.slot_id || ''),
        kind: String(entry.kind || ''), label: label.value, minutes: Number(minutes.value) || 3,
        notes: String(sourceNotes.value || ''), flow_prompt: direction.value, flow: flow,
        apply_kind: !!allOfKind}).then(function (got) {
          sheet.say(String((got && got.say) || 'Segment flow saved.'));
          if (typeof refresh === 'function') setTimeout(refresh, 350);
        }, function (err) { sheet.say(String((err && err.message) || err), true); })
        ['finally'](function () { save.disabled = false; applyKind.disabled = false; });
    }
    save.addEventListener('click', function () { saveFlow(false); });
    applyKind.addEventListener('click', function () { saveFlow(true); });
    render();
    primeSfxNodes();
    loadSystemPrompt();
    loadSavedGraphs();
    return sheet;
  }

  function itineraryFlowSwitch(entry, sheet, refresh) {
    var target = {occurrence: String((entry && entry.occurrence) || ''),
      slot_id: String((entry && entry.slot_id) || '')};
    itineraryClose();
    return itineraryFlowOpen(entry, {returnTarget: target}, refresh);
  }

  function flowEntryHasLine(entry, lineId) {
    var wanted = String(lineId || '');
    if (!wanted) return false;
    var groups = [((entry || {}).script || {}).turns, (entry || {}).aired];
    return groups.some(function (rows) {
      return Array.isArray(rows) && rows.some(function (row) {
        return wanted === String((row || {}).line || '')
          || wanted === String((row || {}).line_id || '')
          || wanted === String((row || {}).id || '');
      });
    });
  }

  function flowEntryForLine(hours, line) {
    var lineId = String((line && line.id) || '');
    var source = elements.find(function (item) {
      return lineId && (String((item || {}).line || '') === lineId
        || String((item || {}).id || '') === lineId);
    }) || {};
    var when = Number((line && line.at) || source.air_at || source.at) || 0;
    var kind = String((line && line.kind) || source.kind || source.round || '').toLowerCase();
    var all = [];
    (hours || []).forEach(function (page) {
      ((page && page.entries) || []).forEach(function (entry) {
        all.push(Object.assign({}, entry, {schedule_preset:
          String(((page && page.sheet) || {}).preset || '')}));
      });
    });
    var exact = all.find(function (entry) { return flowEntryHasLine(entry, lineId); });
    if (exact) return exact;
    var timed = all.filter(function (entry) {
      var start = Number(entry.start) || 0, end = Number(entry.deadline) || 0;
      return when && start && start <= when && (!end || when < end);
    });
    return timed.find(function (entry) { return String(entry.kind || '').toLowerCase() === kind; })
      || timed[0] || all.find(function (entry) {
        return kind && String(entry.kind || '').toLowerCase() === kind;
      }) || null;
  }

  function itineraryFlowForLine(line, close) {
    line = line || {};
    var lineId = String(line.id || '');
    if (!lineId || !api() || !api().get) {
      return Promise.reject(new Error('This item has no scheduled line to trace.'));
    }
    return Promise.all([
      api().get('/api/director?hour=0'), api().get('/api/director?hour=1')
    ]).then(function (hours) {
      var entry = flowEntryForLine(hours.filter(Boolean), line);
      if (!entry) throw new Error('The current running order has no segment for this line.');
      entry.flow_origin = {id: lineId, text: String(line.said || line.text || '').slice(0, 520),
        at: Number(line.at) || 0};
      if (typeof close === 'function') close();
      itineraryClose();
      itineraryFlowOpen(entry, {returnTarget: {occurrence: String(entry.occurrence || ''),
        slot_id: String(entry.slot_id || '')}}, null);
      return entry;
    });
  }

  function itineraryFlowForSegment(ident, close) {
    var block = Number((ident && ident.block) || 0);
    if (!block) return Promise.reject(new Error('This segment has no script block to trace.'));
    return segInspect(block).then(function (data) {
      var first = ((data && data.lines) || []).find(function (line) {
        return String((line || {}).line_id || '');
      });
      if (!first) throw new Error('The segment has no line that can be linked to its schedule.');
      return itineraryFlowForLine({id: String(first.line_id || ''),
        said: String(first.text || ''), text: String(first.text || ''),
        kind: String((data && data.prompt_kind) || (ident && ident.round) || '')}, close);
    });
  }

  root.PineSegmentFlow = {openForLine: itineraryFlowForLine,
    openForSegment: itineraryFlowForSegment};

  function itineraryPaint(list, hours, sheet) {
    for (var h = 0; h < hours.length; h += 1) {
      var page = hours[h] || {};
      var rows = page.entries || [];
      var band = make('div', 'sp-itin-hour');
      var banked = 0, aired = 0, k;
      for (k = 0; k < rows.length; k += 1) {
        if (((rows[k].script || {}).turns || []).length) banked += 1;
        if (String(rows[k].state || '') === 'aired'
            || ((rows[k].aired || []).length)) aired += 1;
      }
      band.appendChild(make('b', 'sp-itin-hour-h',
        h === 0 ? 'THIS HOUR' : 'THE HOUR AFTER'));
      band.appendChild(make('span', 'sp-itin-hour-n',
        rows.length + (rows.length === 1 ? ' entry' : ' entries')
        + '  ·  ' + banked + ' with material banked'
        + '  ·  ' + aired + ' that have aired'
        + (segHas(page.sheet && page.sheet.preset)
          ? '  ·  ' + page.sheet.preset : '')));
      list.appendChild(band);
      if (!rows.length) {
        list.appendChild(make('div', 'sp-segrow-why',
          'The station has no running order for this hour.'));
        continue;
      }
      for (k = 0; k < rows.length; k += 1) {
        var next = rows[k + 1] ? Number(rows[k + 1].start) || 0 : 0;
        var item = Object.assign({}, rows[k] || {}, {
          schedule_preset: String((page.sheet && page.sheet.preset) || '')
        });
        list.appendChild(itinRow(item, next, sheet));
      }
    }
  }

  function itineraryRevealLive(list) {
    var live = list.querySelector('.sp-itin-row[data-state="on air"]');
    if (!live) {
      var now = Date.now() / 1000;
      Array.prototype.some.call(list.querySelectorAll('.sp-itin-row'), function (row) {
        var start = Number(row.dataset.start) || 0;
        var end = Number(row.dataset.deadline) || 0;
        if (start && start <= now && (!end || now < end)) { live = row; return true; }
        return false;
      });
    }
    if (!live) return;
    if (typeof live.__pineOpen === 'function') live.__pineOpen(true);
    root.requestAnimationFrame(function () {
      try { live.scrollIntoView({block: 'center', behavior: 'smooth'}); }
      catch (err) { try { live.scrollIntoView(); } catch (ignore) {} }
      live.classList.add('sp-itin-arrive');
      setTimeout(function () { live.classList.remove('sp-itin-arrive'); }, 1400);
    });
  }

  function itinRow(entry, until, sheet) {
    var state = String(entry.state || '');
    var row = make('div', 'sp-itin-row');
    row.setAttribute('data-state', state);
    row.dataset.start = String(Number(entry.start) || 0);
    row.dataset.deadline = String(Number(entry.deadline) || 0);
    row.dataset.occurrence = String(entry.occurrence || '');
    row.dataset.slot = String(entry.slot_id || '');
    if (state === 'on air') row.classList.add('sp-itin-live');
    else if (state === 'aired' || state.indexOf('went by') === 0) row.classList.add('sp-itin-past');
    row.appendChild(make('span', 'sp-itin-when', itinClock(entry.start) || '--:--'));
    var mid = make('div', 'sp-itin-mid');
    mid.appendChild(make('b', 'sp-itin-name',
      String(entry.label || entry.kind || 'segment')));
    var bits = [];
    if (segHas(entry.kind)) bits.push(String(entry.kind));
    if (segHas(entry.minutes)) bits.push(entry.minutes + ' min');
    if (segHas(entry.slot_id)) bits.push(String(entry.slot_id));
    mid.appendChild(make('span', 'sp-itin-tag', bits.join('  ·  ')));
    var said = itinAired(entry);
    mid.appendChild(make('span', 'sp-itin-hold',
      itinBanked(entry) + (said ? '  ·  ' + said : '')));
    row.appendChild(mid);
    var graphButton = flowIconButton('sp-itin-graph', 'c:chart--network',
      'Design this segment in the node graph');
    graphButton.classList.toggle('has-flow', Array.isArray(entry.flow) && entry.flow.length > 0);
    graphButton.addEventListener('click', function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      itineraryFlowSwitch(entry, sheet, function () {
        var list = document.querySelector('#' + ITIN_ID + ' .sp-itin-list');
        if (list) itineraryHour(list, sheet);
      });
    });
    row.appendChild(graphButton);
    row.appendChild(make('span', 'sp-itin-state', state || 'not said yet'));

    var found = itinFirstLine(entry, until);
    var lid = found ? String(found.line || '') : '';
    row.classList.add(lid ? 'sp-itin-go' : 'sp-itin-nogo');
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    row.title = 'Open this segment’s script, prompt, provenance and broadcast controls';
    var controls = make('div', 'sp-itin-actions');
    var node = lid ? lineNodes.get(segTame(lid)) || lineNode(segTame(lid)) : null;
    var scene = node;
    if (scene) scene = sceneNodes.get(String(scene.dataset.seg || '')) || null;
    var ident = scene ? segIdentity(scene) : null;
    function act(label, run, disabled) {
      var button = make('button', 'sp-itin-action', label);
      button.type = 'button'; button.disabled = !!disabled;
      button.addEventListener('click', function (ev) {
        ev.stopPropagation(); run(button);
      });
      controls.appendChild(button);
    }
    act('Jump to script', function () {
      itineraryClose(); resumeAirFollow('segment navigator'); jumpToLine(lid);
    }, !lid);
    act('Inspect', function () { if (ident) segInspectOpen(ident); }, !ident);
    act('Prompt', function () { if (ident) segPromptOpen(ident); }, !ident);
    act('Download', function () { if (ident) segExportRun(ident, 'welded'); }, !ident);
    act('Run next', function (button) {
      button.disabled = true;
      api().post('/api/dj/segments/interject', {
        slot_id: String(entry.slot_id || ''), kind: String(entry.kind || '')
      }).then(function (got) {
        button.textContent = got && got.ok ? 'Queued next' : String((got && got.why) || 'refused');
        sheet.say(String((got && (got.label || got.why)) || 'segment queued'));
      }, function (err) {
        button.disabled = false; sheet.say((err && err.message) || err, true);
      });
    }, false);
    controls.hidden = true;
    mid.appendChild(controls);
    var conversation = itinConversation(entry, sheet, function () {
      var list = document.querySelector('#' + ITIN_ID + ' .sp-itin-list');
      if (list) itineraryHour(list, sheet);
    });
    conversation.hidden = true;
    row.appendChild(conversation);
    var go = function (ev, force) {
      if (ev) ev.preventDefault();
      if (row.pineFlowHeld) { row.pineFlowHeld = false; return; }
      conversation.hidden = force ? false : !conversation.hidden;
      controls.hidden = conversation.hidden;
      row.setAttribute('aria-expanded', conversation.hidden ? 'false' : 'true');
    };
    row.__pineOpen = function (force) { go(null, force); };
    row.addEventListener('click', go);
    row.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
      go(ev);
    });
    /* Tap reviews the prepared words. Hold opens the operator's flow editor;
       moving a finger first remains ordinary scrolling on the tablet. */
    var hold = null;
    row.addEventListener('pointerdown', function (ev) {
      if (ev.button !== undefined && ev.button > 0) return;
      if (ev.target && ev.target.closest && ev.target.closest('button,input,select,textarea')) return;
      hold = {x: ev.clientX || 0, y: ev.clientY || 0, fired: false};
      hold.timer = setTimeout(function () {
        if (!hold) return;
        hold.fired = true; row.pineFlowHeld = true;
        itineraryFlowSwitch(entry, sheet, function () {
          var list = document.querySelector('#' + ITIN_ID + ' .sp-itin-list');
          if (list) itineraryHour(list, sheet);
        });
      }, SEG_HOLD_MS);
    });
    row.addEventListener('pointermove', function (ev) {
      if (!hold) return;
      if (Math.abs((ev.clientX || 0) - hold.x) > SEG_HOLD_SLOP
          || Math.abs((ev.clientY || 0) - hold.y) > SEG_HOLD_SLOP) {
        clearTimeout(hold.timer); hold = null;
      }
    });
    row.addEventListener('pointerup', function () {
      if (hold) clearTimeout(hold.timer);
      hold = null;
    });
    row.addEventListener('pointercancel', function () {
      if (hold) clearTimeout(hold.timer);
      hold = null;
    });
    row.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      itineraryFlowSwitch(entry, sheet, function () {
        var list = document.querySelector('#' + ITIN_ID + ' .sp-itin-list');
        if (list) itineraryHour(list, sheet);
      });
    });
    if (entry.slot_id) {
      row.draggable = true;
      row.addEventListener('dragstart', function (ev) {
        ev.dataTransfer.setData('text/pine-schedule-slot', String(entry.slot_id));
        row.classList.add('sp-itin-dragging');
      });
      row.addEventListener('dragend', function () { row.classList.remove('sp-itin-dragging'); });
      row.addEventListener('dragover', function (ev) {
        ev.preventDefault(); row.classList.add('sp-itin-drop');
      });
      row.addEventListener('dragleave', function () { row.classList.remove('sp-itin-drop'); });
      row.addEventListener('drop', function (ev) {
        var source = ev.dataTransfer.getData('text/pine-schedule-slot');
        if (!source || source === String(entry.slot_id || '')) return;
        ev.preventDefault(); row.classList.remove('sp-itin-drop');
        itineraryReorder({slot_id: source, schedule_preset: entry.schedule_preset}, entry, sheet,
          function () {
            var list = document.querySelector('#' + ITIN_ID + ' .sp-itin-list');
            if (list) itineraryHour(list, sheet);
          });
      });
    }
    return row;
  }

  function segInspectClose() { var n = el('spSegInspect'); if (n) n.remove(); }

  function segInspectOpen(ident) {
    var sheet = sheetShell('spSegInspect', 'sp-segins',
      'Segment ' + (ident.block ? ident.block : '(unnumbered)'));
    segWindowOpen(sheet, ident);   /* [#1238] a tap in this window is served out of
                                      one answer, not a fresh request each time */
    segFlowInspectButton(sheet, ident);
    segExportButtons(sheet, ident);                         /* [#1220] */
    /* A diagnostic surface: the broadcast ducks while it is open and
       lets go by itself when the sheet leaves the page. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-spSegInspect', root.PineDuck.REPORT, sheet.back);
    }
    var split = make('div', 'sp-segins-split');
    var body = make('div', 'sp-segins-body');
    var side = make('div', 'sp-segins-side');
    split.appendChild(body);
    split.appendChild(side);
    sheet.box.appendChild(split);

    var head = segSection(body, 'The heading');
    segRow(head, 'scene', ident.heading);
    segRow(head, 'block', ident.block, ident.block ? '' : 'no numbered line under it');
    segRow(head, 'hour', ident.hour);
    segRow(head, 'segment id', ident.seg);

    body.appendChild(make('div', 'sp-segins-wait', 'asking the station…'));
    side.appendChild(make('div', 'sp-segflow-note', 'the hand-offs will be drawn here'));

    segInspect(ident.block).then(function (d) {
      if (!el('spSegInspect')) return;          /* closed while asking */
      var wait = body.querySelector('.sp-segins-wait');
      if (wait) wait.remove();
      segFactsPaint(body, d, ident);
      side.textContent = '';
      segFlowPaint(side, d);
      if (d && d.available === false) {
        sheet.say(String(d.why || 'the station has no record of this segment'), true);
      }
    });
    return sheet;
  }

  /* Everything but the sidebar. Every field may be absent; absent is
     printed as absent, with the station's own sentence where it sent
     one. */
  function segFactsPaint(body, d, ident) {
    d = d || {};
    segShown = d;                  /* [#1238] what every tap in here reads */
    if (d.available === false) {
      var gone = segSection(body, 'The station has no record');
      gone.appendChild(make('div', 'sp-segrow-why', String(d.why
        || 'the ledger holds forty-eight hours, and this segment is older than that')));
      return;
    }

    var rnd = d.round || null;
    var round = segSection(body, 'The round');
    if (rnd) {
      segRow(round, 'road', segWord(rnd.road, ident.round || ''));
      segRow(round, 'conversation', rnd.sid);
      segRow(round, 'committed', rnd.committed);
      segRow(round, 'lines', segHas(rnd.lines) ? rnd.lines : null);
      segRow(round, 'scripted', segHas(rnd.scripted) ? rnd.scripted : null,
        'written into the running order before it was said');
      segRow(round, 'welded', segHas(rnd.welded) ? rnd.welded : null,
        'joined on afterwards, not scripted');
    } else {
      round.appendChild(make('div', 'sp-segrow-why',
        'The station carries no round record for this block.'));
    }

    var brief = d.brief || null;
    var bs = segSection(body, 'What this road was supposed to contain');
    if (brief) {
      segRow(bs, 'road', brief.road);
      segRow(bs, 'wants', brief.wants);
      segRow(bs, 'looked for', (brief.looked_for || []).join(', '));
      segRow(bs, 'found', (brief.found || []).join(', '));
      /* met is null when the road has no brief at all; false means the
         station looked for its own words and found none. Those are two
         different answers and must not print the same. */
      segRow(bs, 'met', brief.met === true ? 'yes'
        : (brief.met === false ? 'no' : null),
        (brief.met === null || brief.met === undefined)
          ? 'this road has no brief to meet'
          : (brief.met === false
            ? 'the station looked for its own words and found none'
            : ''));
      if (brief.say) bs.appendChild(make('div', 'sp-segrow-why', String(brief.say)));
    } else {
      bs.appendChild(make('div', 'sp-segrow-why',
        'The station sent no brief for this road.'));
    }

    var t = d.timing || null;
    var ts = segSection(body, 'The timing');
    if (t) {
      segRow(ts, 'first heard', t.first_heard || t.from);
      segRow(ts, 'last heard', t.last_heard || t.to);
      segRow(ts, 'span', segSecs(t.span_s));
      segRow(ts, 'heard', (segHas(t.heard) && segHas(t.of))
        ? (t.heard + ' of ' + t.of) : null);
    } else {
      ts.appendChild(make('div', 'sp-segrow-why', String(d.why
        || 'Not one line of this segment was ever heard, so there is no timing.')));
    }
    var holes = d.holes || [];
    if (holes.length) {
      for (var h = 0; h < holes.length; h += 1) {
        var hole = holes[h] || {};
        var hr = segRow(ts, 'hole', segWord(hole.from, '?') + ' → '
          + segWord(hole.to, '?'), segSecs(hole.seconds));
        hr.classList.add('sp-seghole');
      }
    } else if (t) {
      ts.appendChild(make('div', 'sp-segrow-why',
        'No gap over twelve seconds between consecutive heard lines inside it.'));
    }

    /* WHICH ENTRY ON THE SHEET THIS ROAD IS.
     *
     * Usually not one entry, and that is the truth rather than a gap:
     * the ledger records the ROAD a round was written for and when it
     * was committed, but never the slot it was reserved against - only
     * the live _ready_slot window knew that, and it is gone by the time
     * anybody inspects. So `candidates` is every entry of this road in
     * the running order, `on_air_now` marks the one the clock is
     * standing on, and `slot_id` is filled only when there is exactly
     * one of them. The station's own sentence is printed rather than
     * summarised, here and beside the prompt buttons, because an
     * operator who thinks he has edited ONE entry when he has edited a
     * road will not find out until it is on air. */
    var slot = d.slot || null;
    if (slot) {
      var sl = segSection(body, 'Which entry on the sheet');
      segRow(sl, 'the hour’s sheet', slot.preset);
      segRow(sl, 'this one entry', slot.slot_id,
        segHas(slot.slot_id) ? '' : 'the ledger does not record it');
      var cands = slot.candidates || [];
      for (var c = 0; c < cands.length; c += 1) {
        var cand = cands[c] || {};
        var cr = segRow(sl, cand.on_air_now ? 'on air now' : 'candidate',
          segWord(cand.label, cand.kind) + ' (' + segWord(cand.id, '?') + ')',
          segHas(cand.minutes) ? cand.minutes + ' min' : '');
        if (cand.on_air_now) cr.classList.add('sp-segcand-now');
      }
      if (!cands.length) {
        sl.appendChild(make('div', 'sp-segrow-why',
          'No entry on the running order runs this road.'));
      }
      if (slot.say) sl.appendChild(make('div', 'sp-segrow-why', String(slot.say)));
    }

    /* THE ADMITTED PLAYBACK OCCURRENCE, LINKED BY EVIDENCE.
     *
     * The gate matches a block to an occurrence by the line ids that
     * occurrence admitted (falling back to the words for a welded round
     * whose cue carries no row id), and `lines_matched` says how many
     * landed. One it cannot link it does not claim - so an empty array
     * is not "none", it is the bounded window having moved past this
     * segment, and the station's own sentence says which. */
    var adm = d.admission || null;
    var ps = segSection(body, 'The admitted playback occurrence');
    var occs = (adm && adm.occurrences) || [];
    for (var o = 0; o < occs.length; o += 1) {
      var occ = occs[o] || {};
      var card = make('div', 'sp-segocc');
      segRow(card, 'occurrence', occ.occurrence_id);
      segRow(card, 'position', segHas(occ.position) ? occ.position : null);
      segRow(card, 'state', segWord(occ.state, null) + (segHas(occ.outcome)
        ? '  ·  ' + occ.outcome : ''));
      segRow(card, 'lane', occ.lane);
      segRow(card, 'producer', occ.producer, segHas(occ.origin)
        ? 'origin: ' + occ.origin : '');
      segRow(card, 'lines matched', segHas(occ.lines_matched) ? occ.lines_matched : null,
        'how this occurrence was linked to this block - by its line ids,'
        + ' not by assertion');
      var au = occ.audio || null;
      segRow(card, 'audio', au ? (segWord(au.media, 'no media named')
        + (segHas(au.seconds) ? '  ·  ' + segSecs(au.seconds) : '')
        + (segHas(au.bytes) ? '  ·  ' + au.bytes + ' bytes' : '')) : null,
        au && au.hash_method ? 'hashed by ' + au.hash_method : '');
      segRow(card, 'script revision', occ.script_revision);
      segRow(card, 'performer session', occ.performer_session);
      ps.appendChild(card);
    }
    if (adm && adm.say) ps.appendChild(make('div', 'sp-segrow-why', String(adm.say)));
    else if (!occs.length) {
      ps.appendChild(make('div', 'sp-segrow-why', 'The station did not send'
        + ' one. The per-line air times below are what it does hold.'));
    }

    var seats = d.seats || [];
    var ss = segSection(body, 'Who took part');
    if (seats.length) {
      for (var i = 0; i < seats.length; i += 1) {
        var s = seats[i] || {};
        var look = segSeatLook(s.seat);
        var row = make('div', 'sp-segseat');
        var dot = make('span', 'sp-segflow-dot', '');
        dot.style.background = look.colour;
        row.appendChild(dot);
        row.appendChild(make('b', 'sp-segseat-name', segWord(s.name, look.label)));
        row.appendChild(make('span', 'sp-segseat-seat', look.label));
        row.appendChild(make('span', 'sp-segseat-n',
          (segHas(s.lines)
            ? s.lines + ' line' + (Number(s.lines) === 1 ? '' : 's')
            : 'lines unsaid')
          + (segHas(s.seconds) ? '  ·  ' + segSecs(s.seconds) : '')
          + (segHas(s.heard) ? '  ·  ' + s.heard + ' heard' : '')));
        ss.appendChild(row);
      }
    } else {
      ss.appendChild(make('div', 'sp-segrow-why',
        'The station recorded nobody taking part in this block.'));
    }

    var lines = d.lines || [];
    var ls = segSection(body, 'Every line, in ledger order');
    if (!lines.length) {
      ls.appendChild(make('div', 'sp-segrow-why', 'The station sent no lines.'));
      return;
    }
    for (var j = 0; j < lines.length; j += 1) {
      ls.appendChild(segLineCard(lines[j] || {}));
    }
  }

  /* One line as the station holds it. A line that was written and never
     heard is drawn differently rather than hidden - that is the whole
     reason to be reading this pop-up. */
  function segLineCard(l) {
    var look = segSeatLook(l.who);
    var card = make('div', 'sp-segline');
    if (l.heard === false) card.classList.add('sp-unheard');
    if (String(l.aired || '') === 'withdrawn') card.classList.add('sp-withdrawn');
    card.style.borderLeftColor = look.colour;
    var top = make('div', 'sp-segline-top');
    /* [#1386] THE NAME IS THE HANDLE. "whenever I tap on a title or any
       name or a section inside of the script view, I want the feed to
       become a visual node editor." The line's own body still unfolds the
       record underneath it; the NAME is what traces it. */
    var whoTag = make('b', 'sp-segline-who sp-tracable',
      segWord(l.name, look.label));
    whoTag.title = 'Trace this line - where it came from, and what made it';
    whoTag.addEventListener('click', function (ev) {
      /* The inspector's own cards are not `.sp-el`, so the delegated
         listener above never sees them - this stays, and stops the tap
         before it also unfolds the record underneath. */
      ev.stopPropagation();
      technicalTrace(l.line_id, l.text);
    });
    top.appendChild(whoTag);
    var tags = [];
    if (segHas(l.ord)) tags.push('#' + l.ord);
    if (segHas(l.kind)) tags.push(String(l.kind));
    if (segHas(l.at)) tags.push(String(l.at));
    if (segHas(l.seconds)) tags.push(segSecs(l.seconds));
    tags.push(l.heard === true ? 'heard'
      : (l.heard === false ? 'never heard' : 'heard: not said'));
    tags.push('aired: ' + segWord(l.aired, 'nothing'));
    if (l.scripted === false) tags.push('not scripted');
    top.appendChild(make('span', 'sp-segline-tag', tags.join('  ·  ')));
    card.appendChild(top);
    card.appendChild(make('div', 'sp-segline-text', segWord(l.text, '(no text)')));
    /* [#1386] THE DICE, BESIDE THE LINE THEY MADE.
     *
     * "Next to each piece of dialogue in the script editor, I want to be
     *  able to see the dice roll and the result that it got and the
     *  intensity result of what each dice value equals."
     *
     * The raw roll is shown, not a bucket name, because the bucket is
     * derived and the roll is the fact. The band is shown beside it so a
     * locked range is visible as a range: a 0.12 inside [0, 0.35] is the
     * dice doing what it was told, and a 0.12 inside [0, 1] is chance. */
    if (l.dice && l.dice.roll != null) {
      var d = l.dice;
      var band = Array.isArray(d.band) ? d.band : [0, 1];
      var locked = !(Number(band[0]) === 0 && Number(band[1]) === 1);
      var hard = Number(d.hard || 0);
      var means = hard >= 0.72 ? 'hard' : hard >= 0.36 ? 'plainly' : 'mildly';
      var dice = make('div', 'sp-segline-dice');
      if (locked) dice.classList.add('sp-dice-locked');
      var pip = make('span', 'sp-dice-pip', String(d.roll));
      pip.style.background = Number(d.lean) > 0 ? '#54d18b' : '#e06c9f';
      dice.appendChild(pip);
      dice.appendChild(make('span', 'sp-dice-axis', String(d.axis || 'stance')));
      dice.appendChild(make('span', 'sp-dice-means',
        (Number(d.lean) > 0 ? 'with them' : 'against them') + ' \u00b7 ' + means));
      if (locked) {
        dice.appendChild(make('span', 'sp-dice-band',
          'locked ' + band[0] + '-' + band[1]));
      }
      if (d.answers) {
        dice.appendChild(make('span', 'sp-dice-ans', 'answering #' + d.answers));
      }
      if (d.text) dice.appendChild(make('span', 'sp-dice-text', String(d.text)));
      dice.title = 'rolled ' + d.roll + ' in [' + band[0] + ', ' + band[1] + ']'
        + '  ->  ' + means + (d.text ? ('  ->  ' + d.text) : '');
      card.appendChild(dice);
    }
    var made = [];
    if (segHas(l.voice)) made.push('voice ' + l.voice);
    if (segHas(l.engine)) made.push('engine ' + l.engine);
    if (segHas(l.model)) made.push('model ' + l.model);
    if (segHas(l.source)) made.push('source ' + l.source);
    if (segHas(l.air_at)) made.push('air_at ' + l.air_at);
    if (segHas(l.line_id)) made.push('line ' + l.line_id);
    if (segHas(l.bound_to)) made.push('bound to ' + l.bound_to);   /* [#1237] */
    if (segHas(l.cut_why)) made.push(String(l.cut_why));
    card.appendChild(make('div', 'sp-segline-made',
      made.length ? made.join('  ·  ')
        : 'the station recorded nothing about how this line was made'));
    if (segHas(l.withdrawn_why)) {
      card.appendChild(make('div', 'sp-segline-why',
        'refused at hand-over: ' + String(l.withdrawn_why)));
    }
    /* [#1251] and why the SFX guy chose the clip he chose. The
       station writes this onto the booth row at the moment of the
       draw and airlog_row_from carries it into the durable ledger,
       so it is here for a segment inspected hours later. */
    if (segHas(l.match_why)) {
      var mw = make('div', 'sp-segline-match', String(l.match_why));
      mw.setAttribute('style', 'font-size:11px;color:#7fd6a8');
      card.appendChild(mw);
    }
    segLineWire(card, l);          /* [#1194] tap: on the air. Hold: the sheet. */
    return card;
  }

  /* ---- #1168: the sidebar infographic ----------------------------- */

  /* "a vertical infographic showing guided arrows going from path to
   * path, from person to person representing the conversation
   * transaction taking place and how everyone participated and
   * coalesced ... going down the screen in a sidebar to the right of
   * the pop-up".
   *
   * Drawn with plain elements and no canvas, no animation and no rAF:
   * the tablet's frame pipeline is sensitive (2026-09-14 measured a
   * re-dressed list holding BeginMainFrame at every vsync), and a
   * column of divs costs one layout and then nothing at all. It lives
   * inside the pop-up's own scroller, so it scrolls with it and cannot
   * make the window taller than the glass.
   *
   * `transaction` is the station's ordered hand-offs. The chain is
   * WALKED rather than assumed: where one hand-off's `to` is not the
   * next one's `from`, the break is drawn as a break instead of being
   * quietly stitched over.
   *
   * AND A SEGMENT WITH ONE SPEAKER DRAWS HONESTLY. An empty
   * `transaction` is a real answer - nobody answered anybody - so the
   * sidebar says that and shows who was there, rather than inventing an
   * exchange out of one voice. */
  function segFlowSteps(rows) {
    var steps = [], last = '', i;
    for (i = 0; i < rows.length; i += 1) {
      var from = String((rows[i] && rows[i].from) || '');
      var to = String((rows[i] && rows[i].to) || '');
      if (last === '') steps.push({node: from});
      else if (last !== from) { steps.push({gap: true}); steps.push({node: from}); }
      steps.push({arrow: rows[i] || {}});
      /* [#1238] the seat that ANSWERED, and the hand-off it
         answered with - so a tap on the chip can reach the
         line rather than only naming a seat. */
      steps.push({node: to, tie: rows[i] || null});
      last = to;
    }
    return steps;
  }

  function segFlowChip(seat, tie) {          /* [#1238] tie: the hand-off */
    var look = segSeatLook(seat);
    var chip = make('div', 'sp-segflow-node', '');
    var dot = make('span', 'sp-segflow-dot', '');
    dot.style.background = look.colour;
    chip.appendChild(dot);
    chip.appendChild(make('span', 'sp-segflow-name', look.label));
    chip.style.borderColor = look.colour;
    segFlowTap(chip, seat, tie);   /* [#1238] the node reaches its line */
    return chip;
  }

  function segFlowArrow(t) {
    var wrap = make('div', 'sp-segflow-arrow');
    if (t && t.heard === false) wrap.classList.add('sp-segflow-unheard');
    var stem = make('div', 'sp-segflow-stem', '');
    stem.style.background = segSeatLook(t && t.from).colour;
    wrap.appendChild(stem);
    var head = make('div', 'sp-segflow-head', '');
    head.style.borderTopColor = segSeatLook(t && t.to).colour;
    wrap.appendChild(head);
    var bits = [];
    if (segHas(t && t.kind)) bits.push(String(t.kind));
    if (segHas(t && t.seconds)) bits.push(segSecs(t.seconds));
    if (segHas(t && t.at)) bits.push(String(t.at));
    if (t && t.heard === false) bits.push('never heard');
    var label = make('div', 'sp-segflow-label', bits.join('  ·  ')
      || 'the station said nothing about what passed');
    if (segHas(t && t.text)) label.title = String(t.text).slice(0, 300);
    wrap.appendChild(label);
    segFlowTap(wrap, (t && t.to) || '', t || null);  /* [#1193] so does the arrow */
    return wrap;
  }

  function segFlowPaint(side, d) {
    d = d || {};
    side.appendChild(make('div', 'sp-segflow-h', 'How it was passed around'));
    if (d.available === false) {
      side.appendChild(make('div', 'sp-segflow-note', String(d.why
        || 'the station has no record of this segment, so there is nothing to draw')));
      return;
    }
    var rows = d.transaction || [];
    var seats = d.seats || [];

    /* The legend, from whoever the station says was actually there -
       not from the eight seats in the abstract. */
    var legend = make('div', 'sp-segflow-legend');
    var shown = Object.create(null), k;
    for (k = 0; k < seats.length; k += 1) {
      var look = segSeatLook(seats[k] && seats[k].seat);
      if (shown[look.label]) continue;
      shown[look.label] = 1;
      var key = make('div', 'sp-segflow-key', '');
      var dot = make('span', 'sp-segflow-dot', '');
      dot.style.background = look.colour;
      key.appendChild(dot);
      key.appendChild(make('span', 'sp-segflow-name', look.label));
      if (segHas(seats[k] && seats[k].lines)) {
        key.appendChild(make('span', 'sp-segflow-n', '×' + seats[k].lines));
      }
      legend.appendChild(key);
    }
    if (legend.children.length) side.appendChild(legend);

    if (!rows.length) {
      /* One speaker, or none. Said plainly. */
      if (seats.length === 1) {
        side.appendChild(segFlowChip(seats[0] && seats[0].seat));
        side.appendChild(make('div', 'sp-segflow-note', 'One voice and no'
          + ' hand-off: nobody answered inside this segment, so there is no'
          + ' exchange to draw.'));
      } else if (seats.length > 1) {
        for (var s = 0; s < seats.length && s < SEG_FLOW_MOST; s += 1) {
          side.appendChild(segFlowChip(seats[s] && seats[s].seat));
        }
        side.appendChild(make('div', 'sp-segflow-note', 'The station recorded'
          + ' these seats but no hand-off between them.'));
      } else {
        side.appendChild(make('div', 'sp-segflow-note',
          'The station recorded no hand-offs and nobody taking part.'));
      }
      return;
    }

    var drawn = rows.length > SEG_FLOW_MOST ? rows.slice(0, SEG_FLOW_MOST) : rows;
    var steps = segFlowSteps(drawn);
    for (var i = 0; i < steps.length; i += 1) {
      if (steps[i].node !== undefined) {
        side.appendChild(segFlowChip(steps[i].node, steps[i].tie));  /* [#1238] */
      }
      else if (steps[i].arrow) side.appendChild(segFlowArrow(steps[i].arrow));
      else if (steps[i].gap) {
        side.appendChild(make('div', 'sp-segflow-gap',
          'nothing was recorded between these two'));
      }
    }
    if (rows.length > drawn.length) {
      side.appendChild(make('div', 'sp-segflow-note',
        (rows.length - drawn.length) + ' more hand-off(s) are not drawn:'
        + ' this tablet is kept cheap on purpose.'));
    }
  }

  /* ---- #1168-2: report segment ------------------------------------ */

  /* "pop up report window for reporting segment, extracts script and
   * playback records for report and allows me to dictate / type a
   * report to file".
   *
   * It files down the road the caution button and the #1164 menu
   * already use and no other: reportFire() -> reportGather() for the
   * window, the motion ring and the view snapshot, then POST
   * /api/script/report, then the ten-second post-capture and the
   * picture. So the evidence the caution road gathers rides along
   * without this sheet gathering any of it a second time.
   *
   * THE EXTRACT RIDES IN `reason`, AND ONLY IN `reason`. #1164 wrote
   * down why and it has not changed: normalize_view() excludes unknown
   * fields by schema, so a new key stamped on the view never reaches
   * the .json or the .md, while `reason` is what app.py leads the inbox
   * item with. The station caps it at 1200 characters, so the identity
   * and the operator's own words are written FIRST and the line-by-line
   * digest is appended only while there is room - the part that gets
   * cut is the part he can still read in full in the inspect pop-up. */
  function segReportClose() { var n = el('spSegReport'); if (n) n.remove(); }

  function segReportReason(ident, d, own) {
    d = d || {};
    var parts = ['report segment'];
    if (own) parts.push('what he says: ' + String(own).slice(0, 400));
    if (ident.heading) parts.push('scene: ' + ident.heading);
    parts.push('block: ' + (ident.block || 'none under this heading'));
    var rnd = d.round || null;
    if (rnd) {
      parts.push('round: ' + segWord(rnd.road, ident.round || '?')
        + (segHas(rnd.sid) ? ' (' + rnd.sid + ')' : '')
        + (segHas(rnd.committed) ? ', committed ' + rnd.committed : ''));
    } else {
      parts.push('round: ' + (ident.round || 'unknown')
        + ' (the station sent no round record)');
    }
    /* The inspect route's hour is derived from the round's commit time -
       the hour the segment was WRITTEN in - so it outranks the hour the
       element happened to be painted under. */
    parts.push('hour: ' + (segHas(d.hour) ? d.hour : (ident.hour || 'unknown')));
    if (d.available === false) {
      parts.push('the station has no record of this block: '
        + String(d.why || '').slice(0, 160));
    }
    var t = d.timing || null;
    if (t) {
      parts.push('timing: ' + segWord(t.first_heard || t.from, '?') + ' to '
        + segWord(t.last_heard || t.to, '?') + ', ' + segSecs(t.span_s)
        + ', heard ' + segWord(t.heard, '?') + ' of ' + segWord(t.of, '?'));
    } else if (d.available !== false) {
      parts.push('timing: none - not one line of this segment was heard');
    }
    var holes = d.holes || [];
    if (holes.length) {
      var hs = [];
      for (var h = 0; h < holes.length && h < 6; h += 1) {
        hs.push(segWord(holes[h].from, '?') + '-' + segWord(holes[h].to, '?')
          + ' ' + segSecs(holes[h].seconds));
      }
      parts.push('holes: ' + hs.join(', '));
    }
    /* The occurrence the gate LINKED to this block, by the line ids it
       admitted. It is the one thing in the report that points at the
       audio rather than at the words, so it is named before the digest
       that may be cut. */
    var occs = (d.admission && d.admission.occurrences) || [];
    for (var a = 0; a < occs.length && a < 3; a += 1) {
      var occ = occs[a] || {};
      parts.push('occurrence: ' + segWord(occ.occurrence_id, '?')
        + ' at ' + segWord(occ.position, '?')
        + ', ' + segWord(occ.state, '?') + '/' + segWord(occ.outcome, '?')
        + ', ' + segWord(occ.lines_matched, '?') + ' line(s) matched'
        + (occ.audio && segHas(occ.audio.seconds)
          ? ', ' + segSecs(occ.audio.seconds) + ' of audio' : ''));
    }
    if (!occs.length && d.admission && d.admission.say) {
      parts.push('occurrence: ' + String(d.admission.say).slice(0, 160));
    }
    /* The script and playback extract, appended line by line only while
       it still fits under the station's own cap. */
    var out = parts.join('; ');
    var lines = d.lines || [];
    for (var i = 0; i < lines.length; i += 1) {
      var l = lines[i] || {};
      var sep = (i === 0 ? '; script and playback: ' : ' | ');
      var one = '#' + segWord(l.ord, '?') + ' ' + segWord(l.who, '?')
        + ' ' + segWord(l.kind, '?') + ' ' + segSecs(l.seconds)
        + ' ' + segWord(l.at, 'no air time')
        + ' ' + (l.heard === true ? 'heard'
          : (l.heard === false ? 'NOT heard' : 'heard?'))
        + (segHas(l.withdrawn_why) ? ' withdrawn:' + l.withdrawn_why : '')
        + ' "' + String(l.text || '').replace(/\s+/g, ' ').slice(0, 60) + '"';
      if ((out + sep + one).length > 1180) {
        out += ' | (' + (lines.length - i) + ' more line(s): read them in the'
          + ' inspect pop-up)';
        break;
      }
      out += sep + one;
    }
    return out;
  }

  function segReportOpen(ident) {
    var sheet = sheetShell('spSegReport', 'sp-segrep', 'Report this segment');
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-spSegReport', root.PineDuck.REPORT, sheet.back);
    }
    var who = make('div', 'sp-segrep-who');
    segRow(who, 'scene', ident.heading);
    segRow(who, 'block', ident.block, ident.block ? '' : 'no numbered line under it');
    segRow(who, 'hour', ident.hour);
    sheet.box.appendChild(who);

    var extract = make('div', 'sp-segrep-extract');
    extract.appendChild(make('div', 'sp-segrow-why', 'reading the script and'
      + ' playback records for this segment…'));
    sheet.box.appendChild(extract);

    var ta = make('textarea', 'sp-segrep-ta', '');
    ta.placeholder = 'what is wrong with this segment?';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'Your report about this segment');
    sheet.box.appendChild(ta);

    var tools = make('div', 'sp-segrep-row');
    var dictate = make('button', 'sp-segrep-dictate', '');
    dictate.type = 'button';
    dictate.innerHTML = folderIcon('c:microphone', '');
    dictate.appendChild(document.createTextNode('Dictate'));
    dictate.title = 'Say it: the dot lends its ear and the words land in the box';
    /* The dot's ear, exactly as the reason sheet borrows it - and a
       surface with no microphone says so rather than pretending. */
    dictate.addEventListener('click', function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') {
        sheet.say('no microphone on this surface');
        return;
      }
      try {
        dot.captureNext(function (words) {
          words = String(words || '').trim();
          if (!words) { sheet.say('nothing was heard'); return; }
          ta.value = (ta.value ? String(ta.value).replace(/\s+$/, '') + ' ' : '') + words;
          sheet.say('heard: ' + words.slice(0, 80));
        });
        sheet.say('listening…', true);
      } catch (err) {
        sheet.say('the dot could not listen: '
          + String((err && err.message) || err).slice(0, 80));
      }
    });
    var file = make('button', 'sp-segrep-file', 'File the report');
    file.type = 'button';
    tools.appendChild(dictate);
    tools.appendChild(file);
    sheet.box.appendChild(tools);
    sheet.box.appendChild(make('div', 'sp-segrow-why', 'The window, the motion'
      + ' ring, the view snapshot and the picture the caution button already'
      + ' gathers ride along with it.'));

    var held = null;                    /* the station's record, once read */
    segInspect(ident.block).then(function (d) {
      held = d;
      if (!el('spSegReport')) return;
      extract.textContent = '';
      var lines = (d && d.lines) || [];
      if (d && d.available === false) {
        extract.appendChild(make('div', 'sp-segrow-why', String(d.why
          || 'the station has no record of this segment')));
      } else if (!lines.length) {
        extract.appendChild(make('div', 'sp-segrow-why',
          'The station sent no lines for this block.'));
      } else {
        extract.appendChild(make('div', 'sp-segsec-h', lines.length
          + ' line(s) will be extracted into the report'));
        for (var i = 0; i < lines.length; i += 1) {
          extract.appendChild(segLineCard(lines[i] || {}));
        }
      }
    });

    file.addEventListener('click', function () {
      var own = String(ta.value || '').replace(/\s+/g, ' ').trim();
      if (!own) { sheet.say('say what is wrong, or dictate it'); return; }
      var reason = segReportReason(ident, held, own);
      sheet.close();
      /* The caution road, and the kind the station files it under. */
      reportKind = 'caution';
      try { reportFire(ident.node || el('spScriptName') || document.body, reason); }
      finally { setTimeout(function () { reportKind = 'report'; }, 100); }
    });
    return sheet;
  }

  /* ---- #1168-3: examine system prompt ----------------------------- */

  /* "show system prompt in pop up window allowing for edit and saving
   * as default or new preset for segment prompt. Allow me to modify
   * system prompts for segments."
   *
   * THE STATION ALREADY HAS ALL OF THIS AND NONE OF IT IS REBUILT HERE:
   *
   *   GET  /api/schedule/segment/prompt?hour=&slot=&kind=   what this
   *        entry actually writes with, where those words came from, the
   *        variant shelf, the book that suits it and the dressed clause
   *   GET  /api/schedule/promptbook?kind=                   the book,
   *        newest first
   *   POST /api/schedule/promptbook                         save one
   *        under a name; send an `id` to rewrite one, leave it out to
   *        mint a new one. SAVING CHANGES NOTHING ON AIR.
   *   POST /api/schedule/promptbook/apply                   put one to
   *        work. Its contract, read out of app.py rather than assumed:
   *        {text | id, scope, hour, slot, kind, minutes, name}, scope
   *        one of default | next_segment | next_30 | next_hour.
   *        `default` writes the words onto the kind as a named variant
   *        and pins the entry in the RUNNING ORDER to it - a permanent
   *        change to the plan; name no entry and it arms the variant
   *        for every entry of that kind instead. The three timed scopes
   *        change nothing in the running order at all: they are a note
   *        held beside it, so there is never anything to undo.
   *
   * WHICH IS WHY THERE ARE TWO BUTTONS AND NOT ONE. The station itself
   * keeps saving and applying apart, and the operator has to be able to
   * tell which he is doing: "Save as a new preset" writes to the book
   * and stops - nothing on air moves - and "Save and use for this
   * segment" saves and THEN applies, at a scope he picks, printed in
   * the station's own words for what that scope means. Nothing here
   * ever applies silently on a save.
   *
   * WHICH ENTRY, AND THE SENTENCE THAT SAYS IT IS USUALLY NOT ONE.
   *
   * The entry is named by its KIND, which is what `prompt_kind` off the
   * inspect route is for, and the route answers for that kind in
   * general when no entry is named. The inspect route also sends
   * `slot`, and its `slot_id` is EMPTY most of the time on purpose: the
   * ledger records the road a round was written for and never the slot
   * it was reserved against, because only the live _ready_slot window
   * knew that and it is gone by the time anyone inspects. Several
   * entries usually run one road.
   *
   * So `slot` is sent to the apply road ONLY when `slot_id` is
   * non-empty, and the station's own sentence about it is printed above
   * the two buttons, not paraphrased. A prompt saved "for this segment"
   * reaches the ROAD, and an operator who believes he has edited one
   * entry when he has edited every entry of that road will not find out
   * until he can hear it. Saying so costs one line; not saying so costs
   * an hour of air.
   *
   * The hour is the inspect route's own, which it derives from the
   * round's commit time - the hour the segment was WRITTEN in, which is
   * the one the prompt routes want. Until that answer arrives the
   * element's hour stands in, and either is sent only when it really
   * looks like an hour key; anything else and the station's own default
   * (the hour on air) is the right answer rather than a guess of ours. */
  var SEG_HOUR_RE = /^\d{4}-\d{2}-\d{2}T\d{2}$/;
  var SEG_SCOPE_WHY = {
    'default': 'from now on - it goes into the running order itself and'
      + ' survives a restart',
    'next_segment': 'the next segment of this kind, then it lets go',
    'next_30': 'the next thirty minutes',
    'next_hour': 'the next hour - both thirty-minute halves'
  };

  /* [#1195] THE COMMAND GRAMMAR, as the writing room expands it. The
   * station sends its own list on every answer (`grammar`); this is what
   * the sheet prints before the first answer lands, and if the station is
   * older than the book. Keep the two in step: segment_prompts.GRAMMAR. */
  var SEG_PROMPT_GRAMMAR = [
    {cmd: '- speaker box -', says: 'one random passage out of the speaker box'},
    {cmd: '{{speakbox}}', says: 'the same thing'},
    {cmd: '{{speakbox:doc.md}}', says: 'a passage from that one document'},
    {cmd: '{{speakbox:random:3}}', says: 'three passages, three documents'},
    {cmd: '{{topic}}', says: 'the topic on the table'},
    {cmd: '{{caller}}', says: 'the next caller on the shelf'},
    {cmd: '{{plot}}', says: 'the storyline act that is due'}
  ];

  /* [#1195] One line naming what each command in a call became - the doc
     a speaker box passage came out of, or why nothing came. */
  function segCmdSay(expanded) {
    var bits = [], i;
    for (i = 0; i < ((expanded && expanded.length) || 0) && i < 8; i += 1) {
      var e = expanded[i] || {};
      bits.push(String(e.cmd || '')
        + (e.doc ? ' → ' + String(e.doc)
                 : (e.miss ? ' → ' + String(e.miss) : '')));
    }
    return bits.join(', ');
  }

  function segErrSay(err) {
    return String((err && err.message) || err || 'no reason given').slice(0, 110);
  }

  /* [#1245] An act button: the Carbon mark when the sheet has icons, the
     words always. Never an emoji, and never only an icon. */
  function segAct(cls, icon, text) {
    var b = make('button', cls, '');
    b.type = 'button';
    var mark = make('span', '', '');
    mark.innerHTML = folderIcon(icon, '');
    if (mark.innerHTML) b.appendChild(mark);
    b.appendChild(make('span', '', String(text)));
    return b;
  }


  function segPromptClose() { var n = el('spSegPrompt'); if (n) n.remove(); }

  function segPromptOpen(ident) {
    var sheet = sheetShell('spSegPrompt', 'sp-segpr',
      'The system prompt behind this segment');
    /* NOT ducked. The reason sheet and the inbox duck the broadcast
       because they are diagnostics; this is a preference, the way the
       SFX folder sheet is, and the operator is usually listening to the
       very segment he is rewriting the instruction for. */
    var kind = String(ident.round || '');
    var hour = SEG_HOUR_RE.test(String(ident.hour || '')) ? String(ident.hour) : '';
    var slotId = '';                     /* only when exactly one entry runs this road */
    var picked = null;                   /* the preset loaded into the box */

    var facts = make('div', 'sp-segpr-facts');
    sheet.box.appendChild(facts);
    var ta = make('textarea', 'sp-segpr-ta', '');
    ta.rows = 10;
    ta.placeholder = 'the system prompt this kind of segment writes with';
    ta.setAttribute('aria-label', 'The system prompt for this segment');
    sheet.box.appendChild(ta);

    /* ---------------- [#1245] THE BOX MUST STAY ----------------------
     * "the segment system prompt shows and then it disappears. I need it
     * to stay so I can edit it".  It disappeared because this sheet reads
     * the prompt twice - once for the round the screenplay carries, again
     * for the road segInspect names - and the second answer was painted
     * into the box even when it was EMPTY.  For a round filed under the
     * speaker box document it was seeded from (fmn1.md; 19.6% of the
     * ledger) the second answer is always empty, so the instruction
     * showed and then vanished in front of him.
     *
     * Two rules, and every write to the box goes through taSet so both
     * hold everywhere:
     *   HELD - while the box has focus, or carries an edit that has not
     *     been saved, an arriving answer is PARKED, not painted. The
     *     station can never type over the operator.
     *   NEVER BLANK - an answer with no instruction in it cannot empty a
     *     box that has one. A read that knows nothing leaves what is
     *     there rather than replacing it with a placeholder. */
    var taWas = '';           /* the last words the station or the shelf put in */
    var taDirty = false;      /* he has typed since then */
    var taParked = null;      /* an answer that arrived while he was typing */

    function taMark(on) {
      on = !!on;
      var was = taDirty;
      taDirty = on;
      ta.classList.toggle('sp-segpr-dirty', on);
      if (on && !was) {
        sheet.say('your words are in the box - nothing the station says will'
          + ' overwrite them. Save them, or re-read to throw them away.', true);
      }
    }
    function taHeld() {
      if (taDirty) return true;
      try { return document.activeElement === ta; } catch (err) { return false; }
    }
    function taSet(text, force) {
      text = String(text === undefined || text === null ? '' : text);
      if (!force && taHeld()) { taParked = text; return false; }
      if (!force && !text.trim() && String(ta.value || '').trim()) return false;
      taParked = null;
      ta.value = text;
      taWas = text;
      taMark(false);
      return true;
    }
    ta.addEventListener('input', function () { taMark(ta.value !== taWas); });
    ta.addEventListener('blur', function () { taMark(ta.value !== taWas); });

    /* [#1195] THE COMMANDS, on the sheet. A command nobody is told about
       is a command nobody types. */
    var help = make('div', 'sp-segpr-help', '');
    sheet.box.appendChild(help);
    function helpPaint(rows) {
      help.textContent = '';
      help.appendChild(make('span', '', 'Type a command into the instruction'
        + ' and the writing room fills it in as the segment is written:  '));
      var list = (rows && rows.length) ? rows : SEG_PROMPT_GRAMMAR, i;
      for (i = 0; i < list.length; i += 1) {
        var g = list[i] || {};
        if (i) help.appendChild(make('span', '', '   ·   '));
        help.appendChild(make('code', '', String(g.cmd || '')));
        help.appendChild(make('span', '', ' ' + String(g.says || '')));
      }
    }
    helpPaint(null);

    /* [#1195] WHAT THEY BECOME, before anything is saved or aired. The
       preview draws a passage to show him, and spends nothing: no chunk
       is stamped as served and no pick is recorded. */
    var seeRow = make('div', 'sp-segpr-row');
    var see = segAct('sp-segpr-act', 'c:view', 'See what the commands become');
    see.title = 'Expands the commands in the box without saving or airing'
      + ' anything';
    var reread = segAct('sp-segpr-act', 'c:renew', 'Re-read the instruction');
    reread.title = 'Throw away what is in the box and read the station again';
    seeRow.appendChild(see);
    seeRow.appendChild(reread);
    sheet.box.appendChild(seeRow);
    var seen = make('details', 'sp-segpr-clause');
    seen.hidden = true;
    seen.appendChild(make('summary', '', 'the instruction with its commands filled in'));
    var seenPre = make('pre', 'sp-segpr-pre', '');
    seen.appendChild(seenPre);
    sheet.box.appendChild(seen);

    see.addEventListener('click', function () {
      if (!api() || !api().post) { sheet.say('no bridge to the station'); return; }
      var text = String(ta.value || '');
      if (!text.trim()) { sheet.say('there is nothing in the box to expand'); return; }
      sheet.say('asking the station what these commands become…', true);
      Promise.resolve(api().post('/api/segment/prompts/preview',
          {kind: kind, text: text})).then(function (d) {
        if (!el('spSegPrompt')) return;
        d = d || {};
        seenPre.textContent = String(d.text || '');
        seen.hidden = false;
        seen.open = true;
        var ex = d.expanded || [];
        sheet.say(ex.length
          ? (ex.length + (ex.length === 1 ? ' command' : ' commands')
             + ' filled in: ' + segCmdSay(ex))
          : 'no commands in these words - the writing room gets them as typed',
          true);
      }, function (err) {
        if (!el('spSegPrompt')) return;
        sheet.say('the station could not expand them: ' + segErrSay(err));
      });
    });
    reread.addEventListener('click', function () {
      taWas = ta.value;
      taMark(false);
      try { ta.blur(); } catch (err) { /* no focus to drop */ }
      if (taParked !== null) { var p = taParked; taParked = null; taSet(p, true); }
      promptLoad();
      sheet.say('reading the station again…', true);
    });

    /* -------------- [#1245] THE ALTERNATIVES AND THE DIAL -------------
     * "I want to be able to make and store alternative system prompts
     * that are able to be dialed back and forth and randomised between
     * the segments."  The shelf is per KIND and lives in the station's
     * own book (data/segment_prompts.json), not in this window: what is
     * saved here is what the writing room reads for the NEXT segment of
     * this kind.  The segment on air keeps the instruction it was
     * written with - a round already written cannot be rewritten by
     * changing the shelf, and pretending otherwise would be a lie the
     * operator only finds out about when he listens. */
    var alts = make('div', 'sp-segpr-alts');
    sheet.box.appendChild(alts);
    var usesLine = make('div', 'sp-segpr-uses', '');
    usesLine.hidden = true;
    sheet.box.appendChild(usesLine);
    var altView = null;      /* the station's last shelf answer for this kind */
    var altOpen = '';        /* whose words are in the box */
    var altArmed = '';       /* a bin that has been pressed once */

    function altRoute(tail) {
      return '/api/segment/prompts/' + encodeURIComponent(kind || 'banter') + tail;
    }
    function altAfter(got, said) {
      if (!el('spSegPrompt')) return;
      if (got && got.book) altsPaint(got.book);
      if (said) sheet.say(String(said).slice(0, 240), true);
      promptLoad();          /* which one is dialled now, in the station's words */
    }
    function altPut(body) {
      if (!api() || !api().post) { sheet.say('no bridge to the station'); return; }
      var text = String(ta.value || '');
      if (!text.trim()) { sheet.say('there is nothing in the box to save'); return; }
      body = body || {};
      body.text = text;
      body.name = String(nameIn.value || '').slice(0, 80)
        || (String(kind || 'segment') + ' alternative');
      sheet.say('saving it to the shelf…', true);
      Promise.resolve(api().post(altRoute('/alternative'), body)).then(function (got) {
        if (!el('spSegPrompt')) return;
        var row = (got && got.alternative) || {};
        if (row.id) altOpen = String(row.id);
        taWas = text;
        taMark(false);
        altAfter(got, '“' + String(row.name || 'it') + '” is on the '
          + String((got && got.kind) || kind) + ' shelf - '
          + String(((got && got.book) || {}).says || '')
          + '. The next segment of this kind reads it.');
      }, function (err) {
        if (!el('spSegPrompt')) return;
        sheet.say('the station refused the save: ' + segErrSay(err));
      });
    }
    function altPatch(id, fields) {
      if (!id) return;
      if (!api() || !api().post) { sheet.say('no bridge to the station'); return; }
      Promise.resolve(api().post(altRoute('/alternative/' + encodeURIComponent(id)),
          fields || {})).then(function (got) {
        altAfter(got, String(((got && got.book) || {}).says || 'saved'));
      }, function (err) {
        if (el('spSegPrompt')) sheet.say('the station refused it: ' + segErrSay(err));
      });
    }
    function altDrop(id) {
      if (!id) return;
      if (!api() || !api().del) {
        sheet.say('this surface cannot delete - switch it off instead');
        return;
      }
      Promise.resolve(api().del(altRoute('/alternative/' + encodeURIComponent(id))))
        .then(function (got) {
          if (altOpen === String(id)) altOpen = '';
          altAfter(got, 'taken off the shelf. '
            + String(((got && got.book) || {}).says || ''));
        }, function (err) {
          if (el('spSegPrompt')) sheet.say('the station refused it: ' + segErrSay(err));
        });
    }
    function altMode(mode) {
      if (!api() || !api().post) { sheet.say('no bridge to the station'); return; }
      Promise.resolve(api().post(altRoute('/mode'), {mode: String(mode || '')}))
        .then(function (got) {
          altAfter(got, 'between the segments: '
            + String((got && got.says) || mode));
        }, function (err) {
          if (el('spSegPrompt')) sheet.say('the station refused it: ' + segErrSay(err));
        });
    }

    function altRow(row) {
      var line = make('div', 'sp-segpr-alt');
      if (!row.on) line.classList.add('off');
      if (row.id && String(row.id) === altOpen) line.classList.add('open');
      var open = make('button', 'sp-segpr-altname', '');
      open.type = 'button';
      open.appendChild(make('b', '', String(row.name || row.id || 'Untitled')));
      open.appendChild(make('span', '', 'weight ' + String(row.weight || 1)
        + '  ·  written with ' + String(row.used || 0)
        + (Number(row.used) === 1 ? ' time' : ' times') + '  ·  '
        + String(row.text || '').replace(/\s+/g, ' ').slice(0, 80)));
      open.title = 'Put these words in the box';
      open.addEventListener('click', function () {
        altOpen = String(row.id || '');
        taSet(String(row.text || ''), true);
        nameIn.value = String(row.name || '');
        altsPaint(altView);
        sheet.say('“' + String(row.name || row.id) + '” is in the box'
          + ' - edit it and press Rewrite to change it, or Save as an'
          + ' alternative to make another one', true);
      });
      line.appendChild(open);

      var weight = make('input', 'sp-segpr-weight', '');
      weight.type = 'number';
      weight.min = '1';
      weight.max = '9';
      weight.step = '1';
      weight.value = String(row.weight || 1);
      weight.title = 'How heavily the random draw leans on this one (1-9)';
      weight.setAttribute('aria-label',
        'Weight for ' + String(row.name || 'this alternative'));
      weight.addEventListener('change', function () {
        altPatch(row.id, {weight: Math.max(1, Math.min(9, Number(weight.value) || 1))});
      });
      line.appendChild(weight);

      var sw = make('button', 'sp-segpr-iconbtn', '');
      sw.type = 'button';
      sw.title = row.on ? 'On the dial - switch it off'
                        : 'Switched off - put it back on the dial';
      sw.setAttribute('aria-pressed', row.on ? 'true' : 'false');
      sw.setAttribute('aria-label', sw.title);
      sw.innerHTML = folderIcon(row.on ? 'c:checkbox--checked' : 'c:checkbox', '');
      if (!sw.innerHTML) sw.textContent = row.on ? '[x]' : '[ ]';
      if (row.on) sw.classList.add('on');
      sw.addEventListener('click', function () { altPatch(row.id, {on: !row.on}); });
      line.appendChild(sw);

      /* Two presses to take one off the shelf: the first arms the bin and
         says what it will do, the second does it. Nothing here is
         recoverable, and the shelf is small enough to misclick. */
      var armed = altArmed === String(row.id || '');
      var kill = make('button', 'sp-segpr-iconbtn danger', '');
      kill.type = 'button';
      kill.title = armed ? 'Press again to take it off the shelf'
                         : 'Take it off the shelf';
      kill.setAttribute('aria-label', kill.title);
      kill.innerHTML = folderIcon('c:trash-can', '');
      if (!kill.innerHTML) kill.textContent = armed ? 'sure?' : 'x';
      if (armed) kill.classList.add('on');
      kill.addEventListener('click', function () {
        if (altArmed !== String(row.id || '')) {
          altArmed = String(row.id || '');
          altsPaint(altView);
          sheet.say('press the bin again to take “'
            + String(row.name || row.id) + '” off the shelf', true);
          return;
        }
        altArmed = '';
        altDrop(row.id);
      });
      line.appendChild(kill);
      alts.appendChild(line);
    }

    function altsPaint(view) {
      altView = view || null;
      alts.textContent = '';
      var rows = (view && view.alternatives) || [], i;
      alts.appendChild(make('div', 'sp-segsec-h', 'Alternative instructions'
        + (kind ? ' for ' + kind : '') + ' — ' + rows.length
        + (rows.length === 1 ? ' on the shelf' : ' on the shelf')));
      alts.appendChild(make('div', 'sp-segrow-why', String((view && view.says)
        || 'nothing saved for this kind yet - the words in the box are what'
           + ' it writes with')));
      for (i = 0; i < rows.length; i += 1) altRow(rows[i] || {});

      var dialRow = make('div', 'sp-segpr-row');
      dialRow.appendChild(make('span', 'sp-segrow-k', 'between the segments'));
      var dial = make('select', 'sp-segpr-mode');
      dial.setAttribute('aria-label',
        'How this kind picks between its alternative instructions');
      var opts = [], o;
      for (i = 0; i < rows.length; i += 1) {
        opts.push({v: 'fixed:' + String(rows[i].id || ''),
                   t: 'always “' + String(rows[i].name || '') + '”'});
      }
      opts.push({v: 'cycle', t: 'take the next one in turn, segment by segment'});
      opts.push({v: 'random',
                 t: 'a weighted draw, never the same one twice running'});
      for (i = 0; i < opts.length; i += 1) {
        o = make('option', '', opts[i].t);
        o.value = opts[i].v;
        dial.appendChild(o);
      }
      if (!rows.length) {
        dial.disabled = true;
        dial.title = 'Save an alternative first';
      } else {
        dial.value = String((view && view.mode) || '');
        dial.addEventListener('change', function () { altMode(dial.value); });
      }
      dialRow.appendChild(dial);
      alts.appendChild(dialRow);

      var actRow = make('div', 'sp-segpr-row');
      var keep = segAct('sp-segpr-act lit', 'c:add', 'Save as an alternative');
      keep.title = 'Puts the words in the box on this kind’s shelf as a'
        + ' new alternative. Nothing already written changes.';
      keep.addEventListener('click', function () { altPut({}); });
      actRow.appendChild(keep);
      if (altOpen) {
        var over2 = segAct('sp-segpr-act', 'c:save', 'Rewrite the one I opened');
        over2.title = 'Replaces the words of the alternative loaded into the box';
        over2.addEventListener('click', function () { altPut({id: altOpen}); });
        actRow.appendChild(over2);
      }
      alts.appendChild(actRow);
    }
    altsPaint(null);

    /* [#1195] WHAT THE LAST ROUNDS OF THIS KIND WERE ACTUALLY WRITTEN
       WITH - the paperwork, read back. Two consecutive rounds naming two
       different alternatives is what "randomised between the segments"
       looks like from the outside. */
    function usesPaint(rows) {
      rows = rows || [];
      var bits = [], i;
      for (i = 0; i < rows.length && i < 6; i += 1) {
        var u = rows[i] || {};
        var one = (u.name ? '“' + String(u.name) + '”'
                          : 'the shelf text as it stands')
          + (u.mode ? ' (' + String(u.mode)
                      + (u.of ? ' of ' + String(u.of) : '') + ')' : '');
        if (segCmdSay(u.expanded)) one += ' · ' + segCmdSay(u.expanded);
        bits.push(one);
      }
      usesLine.textContent = bits.length
        ? ('the last segments of this kind were written with:  ' + bits.join('   |   '))
        : '';
      usesLine.hidden = !bits.length;
    }


    var namely = make('div', 'sp-segpr-row');
    var nameIn = make('input', 'sp-segpr-in', '');
    nameIn.type = 'text';
    nameIn.placeholder = 'a name for this preset';
    nameIn.setAttribute('aria-label', 'The preset name');
    var scenIn = make('input', 'sp-segpr-in', '');
    scenIn.type = 'text';
    scenIn.placeholder = 'when to use it';
    scenIn.setAttribute('aria-label', 'When to use this preset');
    namely.appendChild(nameIn);
    namely.appendChild(scenIn);
    sheet.box.appendChild(namely);

    /* Rewriting the preset he opened is a different act from minting a
       new one, and the route draws that line with `id`. So does this,
       and it is off until he says otherwise. */
    var overRow = make('div', 'sp-segpr-row sp-segpr-over');
    overRow.hidden = true;
    var over = make('button', 'sp-segpr-tick', '');
    over.type = 'button';
    over.setAttribute('aria-pressed', 'false');
    var overMark = make('span', 'sp-segpr-tickmark', '');
    over.appendChild(overMark);
    over.appendChild(make('span', 'sp-segpr-tickt',
      'rewrite the preset I opened instead of minting a new one'));
    overRow.appendChild(over);
    sheet.box.appendChild(overRow);
    function overPaint() {
      var on = over.getAttribute('aria-pressed') === 'true';
      overMark.innerHTML = folderIcon(on ? 'c:checkbox--checked' : 'c:checkbox', '');
      if (!overMark.innerHTML) overMark.textContent = on ? '[x]' : '[ ]';
      over.classList.toggle('on', on);
    }
    over.addEventListener('click', function () {
      over.setAttribute('aria-pressed',
        over.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      overPaint();
    });
    overPaint();

    var scopeRow = make('div', 'sp-segpr-row');
    scopeRow.appendChild(make('span', 'sp-segrow-k', 'and use it for'));
    var scope = make('select', 'sp-segpr-scope');
    scope.setAttribute('aria-label', 'How long the applied prompt holds');
    scopeRow.appendChild(scope);
    sheet.box.appendChild(scopeRow);
    var scopeWhy = make('div', 'sp-segrow-why', '');
    sheet.box.appendChild(scopeWhy);

    /* WHO THIS REACHES, IN THE STATION'S OWN WORDS, ABOVE THE BUTTONS.
       Filled from the inspect route's `slot.say` - "3 entries on the
       sheet run this road; ... a prompt saved for this segment reaches
       the road rather than one entry" - because that is the one thing
       about these two buttons an operator could get wrong. */
    var reach = make('div', 'sp-segpr-reach', '');
    reach.hidden = true;
    sheet.box.appendChild(reach);

    var buttons = make('div', 'sp-segpr-row');
    var save = make('button', 'sp-segpr-save', 'Save as a new preset');
    save.type = 'button';
    save.title = 'Writes it into the prompt book. Nothing on air changes.';
    var apply = make('button', 'sp-segpr-apply', 'Save and use for this segment');
    apply.type = 'button';
    apply.title = 'Saves it AND puts it to work, at the scope chosen above';
    buttons.appendChild(save);
    buttons.appendChild(apply);
    sheet.box.appendChild(buttons);

    var book = make('div', 'sp-segpr-book');
    sheet.box.appendChild(book);

    function scopeSay() {
      var opt = scope.options[scope.selectedIndex];
      scopeWhy.textContent = (opt && opt.pineWhy)
        || SEG_SCOPE_WHY[scope.value] || '';
    }
    function scopePaint(scopes) {
      scope.textContent = '';
      var order = ['next_segment', 'next_30', 'next_hour', 'default'], i;
      for (i = 0; i < order.length; i += 1) {
        var id = order[i];
        var said = (scopes && scopes[id]) || SEG_SCOPE_WHY[id] || id;
        var opt = make('option', '',
          id === 'default' ? 'the standing instruction' : said);
        opt.value = id;
        opt.pineWhy = said;
        scope.appendChild(opt);
      }
      scope.value = 'next_segment';
      scopeSay();
    }
    scope.addEventListener('change', scopeSay);
    scopePaint(null);

    function bookPaint(rows) {
      book.textContent = '';
      var h = make('div', 'sp-segsec-h', 'The prompt book'
        + (kind ? ', for ' + kind : '') + ' — newest first');
      var again = make('button', 'sp-segpr-again', '');
      again.type = 'button';
      again.innerHTML = folderIcon('c:renew', 'Read the book again');
      if (!again.innerHTML) again.textContent = 'refresh';
      again.title = 'Read the prompt book again';
      again.addEventListener('click', bookLoad);
      h.appendChild(again);
      book.appendChild(h);
      if (!rows || !rows.length) {
        book.appendChild(make('div', 'sp-segrow-why',
          'Nothing saved for this kind yet.'));
        return;
      }
      for (var i = 0; i < rows.length && i < 40; i += 1) {
        (function (row) {
          var b = make('button', 'sp-segpr-preset', '');
          b.type = 'button';
          b.appendChild(make('b', '', String(row.name || row.id || 'unnamed')));
          b.appendChild(make('span', 'sp-segpr-presetwhy',
            (row.kind ? String(row.kind) : 'suits anything')
            + (row.scenario ? '  ·  ' + String(row.scenario) : '')));
          b.addEventListener('click', function () {
            taSet(String(row.text || ''), true);   /* [#1245] one road in */
            nameIn.value = String(row.name || '');
            scenIn.value = String(row.scenario || '');
            picked = row;
            overRow.hidden = false;
            sheet.say('opened “' + String(row.name || row.id) + '”'
              + ' — nothing has been saved or applied');
          });
          book.appendChild(b);
        })(rows[i] || {});
      }
    }

    function bookLoad() {
      if (!api() || !api().get) { sheet.say('no bridge to the station'); return; }
      Promise.resolve(api().get('/api/schedule/promptbook'
          + (kind ? '?kind=' + encodeURIComponent(kind) : ''))).then(function (d) {
        if (!el('spSegPrompt')) return;
        bookPaint((d && d.prompts) || []);
      }, function (err) {
        if (!el('spSegPrompt')) return;
        book.textContent = '';
        book.appendChild(make('div', 'sp-segrow-why', 'the book could not be'
          + ' read: ' + String((err && err.message) || err).slice(0, 90)));
      });
    }

    function promptLoad() {
      if (!api() || !api().get) {
        facts.textContent = '';
        facts.appendChild(make('div', 'sp-segrow-why',
          'There is no bridge to the station from this surface.'));
        return;
      }
      facts.textContent = '';
      facts.appendChild(make('div', 'sp-segrow-why', 'asking the station…'));
      var q = '/api/schedule/segment/prompt?kind=' + encodeURIComponent(kind);
      if (hour) q += '&hour=' + encodeURIComponent(hour);
      Promise.resolve(api().get(q)).then(function (d) {
        if (!el('spSegPrompt')) return;
        d = d || {};
        facts.textContent = '';
        segRow(facts, 'segment', segWord(d.label, kind || ident.heading));
        segRow(facts, 'kind', segWord(d.kind, kind));
        segRow(facts, 'hour', segWord(d.hour, hour || 'the hour on air'));
        segRow(facts, 'these words came from', d.source);
        /* [#1245] The two facts that made this box look empty: a round
           filed under the speaker box DOCUMENT it was seeded from
           (fmn1.md) is keyed on a ROAD, and the road is what has a shelf.
           And which alternative the dial has landed on for the next one. */
        if (d.road && String(d.road) !== String(d.kind || '')) {
          segRow(facts, 'the road it is keyed on', d.road);
        }
        if (d.seed_doc) segRow(facts, 'seeded from the speaker box', d.seed_doc);
        if (d.dialled) {
          segRow(facts, 'the alternative dialled for the next one',
            String(d.dialled.name || d.dialled.id || ''))
            .classList.add('sp-segpr-pick');
        }
        if (d.variant) segRow(facts, 'variant', d.variant.name || d.variant.id);
        if (d.window) {
          var w = segRow(facts, 'a timed prompt owns this kind',
            String(d.window.name || ''), String(d.window.says || ''));
          w.classList.add('sp-seghole');
        }
        if (d.why) facts.appendChild(make('div', 'sp-segrow-why', String(d.why)));
        if (d.blurb) facts.appendChild(make('div', 'sp-segrow-why', String(d.blurb)));
        /* [#1245] THE BOX IS FILLED WITH WHAT THE WRITING ROOM WOULD
           ACTUALLY BE HANDED for the next segment of this kind - the
           alternative the dial lands on, else the shelf text, else the
           station's own seed - and it is filled through taSet, so an
           answer that arrives while he is typing is parked instead of
           painted over him, and an answer with nothing in it can no
           longer empty a box that has something. This is the line that
           made the prompt "show and then disappear". */
        var want = String(d.text || '');
        if (!want.trim()) want = String(d.seed || '');
        var landed = taSet(want);
        if (!landed && taHeld()) {
          sheet.say('the station answered while you were typing - your words'
            + ' are still in the box. Re-read to take the station’s.', true);
        } else if (!landed) {
          sheet.say('the station has no instruction for this kind just now -'
            + ' what is in the box is left as it is', true);
        } else if (!String(d.text || '').trim() && d.seed) {
          sheet.say('there is nothing on the shelf for this kind; the'
            + ' station’s own seed is in the box', true);
        }
        helpPaint(d.grammar);                                    /* [#1195] */
        altsPaint(d.alternatives || null);                       /* [#1245] */
        usesPaint(d.uses || []);                                 /* [#1195] */
        if (!nameIn.value) {
          nameIn.value = String(d.label || d.kind || kind || 'segment')
            + (ident.block ? ' · block ' + ident.block : '');
        }
        if (d.scopes) scopePaint(d.scopes);
        if (d.clause) {
          var cl = make('details', 'sp-segpr-clause');
          cl.appendChild(make('summary', '',
            'the dressed clause, as the writing room receives it'));
          cl.appendChild(make('pre', 'sp-segpr-pre', String(d.clause)));
          facts.appendChild(cl);
        }
        bookPaint(d.book || []);
      }, function (err) {
        if (!el('spSegPrompt')) return;
        facts.textContent = '';
        facts.appendChild(make('div', 'sp-segrow-why', 'the station did not'
          + ' answer: ' + String((err && err.message) || err).slice(0, 110)));
      });
    }

    /* SAVE. The book, and only the book. */
    function saveIt() {
      var text = String(ta.value || '');
      if (!text.trim()) { sheet.say('there is nothing in the box to save'); return null; }
      if (!api() || !api().post) { sheet.say('no bridge to the station'); return null; }
      var body = {name: String(nameIn.value || '').slice(0, 80), kind: kind,
        scenario: String(scenIn.value || '').slice(0, 200), text: text};
      /* An `id` rewrites that one; without it the station mints a new
         one. The tick above is the only thing that sends an id. */
      if (picked && picked.id && over.getAttribute('aria-pressed') === 'true') {
        body.id = String(picked.id);
      }
      return Promise.resolve(api().post('/api/schedule/promptbook', body));
    }

    save.addEventListener('click', function () {
      var ask = saveIt();
      if (!ask) return;
      sheet.say('saving…', true);
      ask.then(function (got) {
        if (!el('spSegPrompt')) return;
        var row = (got && got.prompt) || {};
        if (row.id) { picked = row; overRow.hidden = false; }
        bookPaint((got && got.book && got.book.prompts) || []);
        sheet.say('saved to the book as “'
          + String(row.name || nameIn.value || 'it')
          + '”. Nothing on air has changed.', true);
      }, function (err) {
        if (!el('spSegPrompt')) return;
        sheet.say('the station refused the save: '
          + String((err && err.message) || err).slice(0, 90));
      });
    });

    /* SAVE AND USE. Two acts, in that order, and the second one is
       named out loud in the station's own words when it lands. */
    apply.addEventListener('click', function () {
      var ask = saveIt();
      if (!ask) return;
      var want = String(scope.value || 'next_segment');
      sheet.say('saving, then applying…', true);
      ask.then(function (got) {
        var row = (got && got.prompt) || {};
        if (el('spSegPrompt')) {
          if (row.id) { picked = row; overRow.hidden = false; }
          bookPaint((got && got.book && got.book.prompts) || []);
        }
        var body = {scope: want, kind: kind, text: String(ta.value || ''),
          name: String(nameIn.value || '').slice(0, 80)};
        /* The id makes `default` rewrite this preset's own variant
           rather than piling up a new one every time it is applied. */
        if (row.id) body.id = String(row.id);
        if (hour) body.hour = hour;
        /* ONLY when the station said exactly one entry runs this road.
           Naming a slot it did not name would pin a prompt to an entry
           on a guess, and the apply road 404s an entry that is not in
           that hour - both worse than letting it reach the road, which
           is what the sentence above the buttons already says it will
           do. */
        if (slotId) body.slot = slotId;
        if (want === 'next_30') body.minutes = 30;
        if (want === 'next_hour') body.minutes = 60;
        return Promise.resolve(api().post('/api/schedule/promptbook/apply', body));
      }).then(function (got) {
        if (!el('spSegPrompt')) return;
        if (!got || got.ok === false) {
          sheet.say('saved, but not applied: '
            + String((got && got.say) || 'the station refused it'), true);
          return;
        }
        sheet.say('saved, and now in force: ' + String(got.says || want)
          + (segHas(got.entries) ? ' (' + got.entries + ' entry/entries)' : ''), true);
      }, function (err) {
        if (!el('spSegPrompt')) return;
        sheet.say('the station refused it: '
          + String((err && err.message) || err).slice(0, 110));
      });
    });

    /* The scene's own round and hour paint the window at once, because
       a window that waits on a second read is a window that looks
       broken for a beat. The inspect route is then asked for the three
       things only it knows for certain - the road (`prompt_kind`), the
       hour the segment was WRITTEN in, and which entry, if any, this
       reaches - and the window is read again only if one of them
       actually differs. segInspect holds its answer for twenty seconds,
       so inspecting and then opening this costs one question, not
       two. */
    promptLoad();
    segInspect(ident.block).then(function (d) {
      if (!el('spSegPrompt')) return;
      d = d || {};
      var again = false;
      var road = String(d.prompt_kind || '');
      if (road && road !== kind) { kind = road; again = true; }
      if (SEG_HOUR_RE.test(String(d.hour || '')) && String(d.hour) !== hour) {
        hour = String(d.hour);
        again = true;
      }
      var slot = d.slot || null;
      slotId = String((slot && slot.slot_id) || '');
      if (slot && slot.say) {
        reach.textContent = String(slot.say);
        reach.hidden = false;
        /* One entry is the quiet case; a road with several entries on
           the sheet is the one he has to read, so it is marked. */
        reach.classList.toggle('sp-segpr-wide', !slotId);
      }
      if (again) promptLoad();
    });
    return sheet;
  }

  /* ---- #1220: download the whole segment ------------------------- */

  /* "I want to be able to download an entire segment, offer an option to
   * download the whole segment and export it to Pinebox for recordings
   * as a segment."
   *
   * The station builds the file (POST /api/export/segment: every heard
   * line of the block in ledger order, cut from the round's own welded
   * audio with the stings where they fell, records as short beds) and
   * hands it to the courier, which is what carries anything to the
   * PineBoxRecordings folder (#1114). This only asks, then watches the
   * job (GET /api/export/segment/<job>) in a toast at the corner of the
   * glass that says which step it is on and, at the end, where the file
   * landed. "As it aired" asks for the same stretch off the broadcast
   * shelf's full mix; a stretch the shelf has not sealed yet comes back
   * refused with `can_seal`, and the toast offers to seal it first. */
  var SEG_EXPORT_POLL_MS = 1500;
  var SEG_EXPORT_MAX_MS = 15 * 60 * 1000;
  var SEG_EXPORT_RAIL_ID = 'spSegExportRail';

  function segExportToast(title) {
    var rail = el(SEG_EXPORT_RAIL_ID);
    if (!rail) {
      rail = make('div', 'sp-segexp-rail');
      rail.id = SEG_EXPORT_RAIL_ID;
      document.body.appendChild(rail);
    }
    var box = make('div', 'sp-segexp');
    var head = make('div', 'sp-segexp-head');
    head.appendChild(make('b', null, title));
    var x = make('button', 'sp-segexp-x', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    head.appendChild(x);
    box.appendChild(head);
    var bar = make('div', 'sp-segexp-bar');
    var fill = make('div', 'sp-segexp-fill');
    bar.appendChild(fill);
    box.appendChild(bar);
    var step = make('div', 'sp-segexp-step', 'asking the station\u2026');
    box.appendChild(step);
    var where = make('div', 'sp-segexp-where', '');
    where.hidden = true;
    box.appendChild(where);
    var acts = make('div', 'sp-segexp-acts');
    acts.hidden = true;
    box.appendChild(acts);
    rail.appendChild(box);
    while (rail.children.length > 3) rail.removeChild(rail.children[0]);
    var gone = 0;
    function close() {
      clearTimeout(gone);
      if (box.parentNode) box.parentNode.removeChild(box);
      var r = el(SEG_EXPORT_RAIL_ID);
      if (r && !r.children.length && r.parentNode) r.parentNode.removeChild(r);
    }
    x.addEventListener('click', close);
    return {
      box: box, close: close,
      open: function () { return !!box.parentNode; },
      pct: function (p) {
        var n = Number(p);
        if (!isFinite(n)) n = 0;
        fill.style.width = Math.max(0, Math.min(100, n)) + '%';
      },
      say: function (text, bad) {
        step.textContent = String(text || '');
        step.classList.toggle('bad', !!bad);
      },
      where: function (text) {
        where.textContent = String(text || '');
        where.hidden = !where.textContent;
      },
      done: function (ms) {
        clearTimeout(gone);
        gone = setTimeout(close, ms || 15000);
      },
      button: function (label, act) {
        var b = make('button', 'sp-segexp-btn', label);
        b.type = 'button';
        b.addEventListener('click', function () { acts.hidden = true; act(); });
        acts.appendChild(b);
        acts.hidden = false;
        return b;
      }
    };
  }

  function segExportRun(ident, source, extra) {
    ident = ident || {};
    source = source === 'aired' ? 'aired' : 'welded';
    var block = String(ident.block || '').trim();
    var toast = segExportToast('Segment ' + (block || '(unnumbered)') + ' \u00b7 '
      + (source === 'aired' ? 'as it aired' : 'the whole segment'));
    if (!block) {
      toast.say('No line under this heading carries a block number, so there is'
        + ' nothing to download - a segment is named by its block (#1330).', true);
      toast.done(9000);
      return Promise.resolve(null);
    }
    if (!api() || !api().post || !api().get) {
      toast.say('There is no bridge to the station from this surface.', true);
      toast.done(9000);
      return Promise.resolve(null);
    }
    var body = {block: Number(block), source: source, records: 'short'};
    if (extra && typeof extra === 'object') {
      Object.keys(extra).forEach(function (k) { body[k] = extra[k]; });
    }
    toast.pct(3);
    var startedAt = Date.now();
    function paint(d) {
      d = d || {};
      toast.pct(d.pct);
      var st = String(d.state || '');
      if (st === 'ready') {
        toast.pct(100);
        toast.say(String(d.say || 'landed'));
        toast.where(String(d.landed || d.share_path || d.path || ''));
        toast.done(20000);
        return true;
      }
      if (st === 'failed' || st === 'empty') {
        toast.say(String(d.say || d.error || 'the station could not build it'), true);
        if (d.can_seal) {
          toast.button('Seal the shelf now and build it', function () {
            toast.close();
            segExportRun(ident, source, {seal: true});
          });
        }
        if (source === 'aired') {
          toast.button('Build the welded segment instead', function () {
            toast.close();
            segExportRun(ident, 'welded');
          });
        } else if (!d.can_seal) {
          toast.done(14000);
        }
        return true;
      }
      toast.say(String(d.step || d.say || 'building\u2026'));
      return false;
    }
    function poll(job) {
      if (!toast.open()) return;                 /* closed by hand: stop asking */
      if (Date.now() - startedAt > SEG_EXPORT_MAX_MS) {
        toast.say('the station is still building it; the file lands in the'
          + ' recording folder when it is done', true);
        return;
      }
      Promise.resolve(api().get('/api/export/segment/' + encodeURIComponent(job)))
        .then(function (d) {
          if (!paint(d)) setTimeout(function () { poll(job); }, SEG_EXPORT_POLL_MS);
        }, function (err) {
          toast.say('the station did not answer: '
            + String((err && err.message) || err).slice(0, 120), true);
          setTimeout(function () { poll(job); }, SEG_EXPORT_POLL_MS * 3);
        });
    }
    return Promise.resolve(api().post('/api/export/segment', body)).then(function (got) {
      got = got || {};
      if (!got.job) {
        toast.say(String(got.say || got.detail || 'the station refused it'), true);
        toast.done(12000);
        return got;
      }
      if (!paint(got)) poll(got.job);
      return got;
    }, function (err) {
      toast.say('the station refused it: '
        + String((err && err.message) || err).slice(0, 160), true);
      toast.done(12000);
      return null;
    });
  }

  function segFlowInspectButton(sheet, ident) {
    if (!sheet || !sheet.head || !sheet.x) return;
    var graph = flowIconButton('sp-segins-flow', 'c:chart--network',
      'Open this inspected segment in the node graph');
    graph.addEventListener('click', function () {
      graph.disabled = true;
      itineraryFlowForSegment(ident, sheet.close)['catch'](function (err) {
        graph.disabled = false;
        sheet.say(String((err && err.message) || err), true);
      });
    });
    sheet.head.insertBefore(graph, sheet.x);
  }

  /* The Segment window's own header carries the same two roads, so a
     segment being inspected can be taken away without going back to the
     menu. Inserted before the close button, which sheetShell owns. */
  function segExportButtons(sheet, ident) {
    if (!sheet || !sheet.head || !sheet.x) return;
    function one(icon, label, short, source) {
      var b = make('button', 'sp-segins-dl', '');
      b.type = 'button';
      b.title = label;
      b.setAttribute('aria-label', label);
      b.innerHTML = folderIcon(icon, '') || '';
      b.appendChild(make('span', 'sp-segins-dl-text', short));
      b.addEventListener('click', function () { segExportRun(ident, source); });
      sheet.head.insertBefore(b, sheet.x);
    }
    one('c:download', 'Download the whole segment to the recording folder',
      'download', 'welded');
    one('c:recording--filled', 'Download the segment as it aired, off the broadcast shelf',
      'as aired', 'aired');
  }

  /* ---- #1168: the menu itself ------------------------------------- */

  var SEG_CHOICES = [
    {id: 'inspect', label: 'Inspect segment', icon: 'c:microscope',
     why: 'Every aspect of how this segment was composed, with the'
        + ' conversation drawn down the side'},
    {id: 'report', label: 'Report segment', icon: 'c:receipt',
     why: 'File a report about this segment - its script and playback'
        + ' records ride along'},
    {id: 'prompt', label: 'Examine system prompt', icon: 'c:book',
     why: 'The system prompt this kind of segment writes with: read it,'
        + ' edit it, save it, or put it to work'},
    /* [#1220] the two downloads: the station builds one file for the
       block and the courier carries it to the recording folder. */
    {id: 'export', label: 'Download the whole segment', icon: 'c:download',
     why: 'One file in the recording folder: every heard line of this'
        + ' segment in script order, cut from the round\'s own audio with'
        + ' the stings where they fell, records as short beds'},
    {id: 'export-air', label: 'Download the segment as it aired',
     icon: 'c:recording--filled',
     why: 'The same stretch off the broadcast shelf\'s full mix - records'
        + ' underneath, gaps as they were - once the shelf has sealed it'}
  ];

  function segMenuClose() {
    var menu = el(SEG_MENU_ID);
    if (menu) menu.remove();
    if (segMenuUnwatch) {
      try { segMenuUnwatch(); } catch (err) { /* already gone */ }
      segMenuUnwatch = null;
    }
  }

  function segMenuOpen(node) {
    if (!node) return null;
    segMenuClose();
    var ident = segIdentity(node);

    var menu = make('div', 'sp-segmenu');
    menu.id = SEG_MENU_ID;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'This segment');

    /* No say line of its own: this menu says nothing, it only opens
       three windows that each have one. A message that could never
       appear is a message the reader has to work out is dead. */
    menu.appendChild(make('div', 'sp-segmenu-where',
      (ident.block ? 'block ' + ident.block : 'no block number under this heading')
      + (ident.round ? '  ·  ' + ident.round : '')));

    function row(choice) {
      var b = make('button', 'sp-segmenu-item', '');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.dataset.seg = choice.id;
      var mark = make('span', 'sp-segmenu-mark', '');
      mark.innerHTML = folderIcon(choice.icon, '');
      if (!mark.innerHTML) mark.textContent = '·';
      b.appendChild(mark);
      b.appendChild(make('span', 'sp-segmenu-text', choice.label));
      b.title = choice.why;
      b.addEventListener('click', function () {
        segMenuClose();
        try {
          if (choice.id === 'inspect') segInspectOpen(ident);
          else if (choice.id === 'report') segReportOpen(ident);
          else if (choice.id === 'export') segExportRun(ident, 'welded');     /* [#1220] */
          else if (choice.id === 'export-air') segExportRun(ident, 'aired');  /* [#1220] */
          else segPromptOpen(ident);
        } catch (err) {
          caughtNote('seg:' + choice.id, err);
          say('that window could not be opened: '
            + String((err && err.message) || err).slice(0, 80));
        }
      });
      return b;
    }
    for (var i = 0; i < SEG_CHOICES.length; i += 1) menu.appendChild(row(SEG_CHOICES[i]));

    var cancel = make('button', 'sp-segmenu-item sp-segmenu-cancel', '');
    cancel.type = 'button';
    cancel.setAttribute('role', 'menuitem');
    var cmark = make('span', 'sp-segmenu-mark', '');
    cmark.innerHTML = folderIcon('c:close--filled', '');
    if (!cmark.innerHTML) cmark.textContent = '·';
    cancel.appendChild(cmark);
    cancel.appendChild(make('span', 'sp-segmenu-text', 'Cancel'));
    cancel.title = 'Close this menu and do nothing';
    cancel.addEventListener('click', segMenuClose);
    menu.appendChild(cancel);

    document.body.appendChild(menu);
    /* Fixed, at the heading's own corner, clamped inside the glass -
       the tablet's is 1154x690 CSS px, and a menu hanging off the
       bottom of it is a menu with an item the thumb cannot reach. */
    try {
      var seat = headerSeat(node);
      var gw = (root.innerWidth || 1154), gh = (root.innerHeight || 690);
      var mw = menu.offsetWidth || 300, mh = menu.offsetHeight || 220;
      var left = Math.max(6, Math.min(gw - mw - 6, (seat.left || 0)));
      var top = (seat.bottom || 0) + 4;
      if (top + mh > gh - 6) top = Math.max(6, (seat.top || 0) - mh - 4);
      if (top + mh > gh - 6) top = Math.max(6, gh - mh - 6);
      menu.style.left = Math.round(left) + 'px';
      menu.style.top = Math.round(top) + 'px';
    } catch (err) { /* no geometry on this surface; the CSS stands */ }

    /* It opens two diagnostics and files reports, so it ducks - and the
       hold is tied to the menu, so PineDuck gives the radio back by
       itself the moment the menu leaves the page. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-' + SEG_MENU_ID, root.PineDuck.REPORT, menu);
    }
    /* Tap away and Escape, through the one rule every other pop-up on
       this page is on. The heading is spared so its own hold re-opens
       rather than close-then-open. */
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      segMenuUnwatch = root.PineDismiss.watch(menu, segMenuClose, [node], function () {
        return !!el(SEG_MENU_ID);
      });
    }
    return menu;
  }

  /* ---- #1385: the word search ------------------------------------ */

  /* The station does the counting (/api/said/search, #1380); this only
   * draws what it said. A sheet over the view, tap away to close, the
   * same shape as the clip doctor's - the operator asked for it on the
   * tablet, so every control is a thumb's size. */
  function findClose() {
    var old = el('spFindSheet');
    if (old) old.remove();
  }

  function findOpen(q) {
    q = String(q || '').trim();
    if (q.length < 2 || !api() || !api().get) return;
    findClose();
    var back = make('div', 'sp-find-back');
    back.id = 'spFindSheet';
    var box = make('div', 'sp-find-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, '\u201c' + q + '\u201d on the air'));
    /* [#1241] "an icon here for tracing a typed phrase through the prompts,
       the data crystal, the topics, the scripts, and find the source of
       where a scripted phrase is coming from", and [#1239] "a trash can so
       that whenever I search for [it] I'm able to delete [it] ... and have
       it not said by the host anymore". Both live in the head of the sheet
       the operator is already looking at. */
    var traceBtn = findHeadBtn('c:chart--network', 'Where it comes from');
    var banBtn = findHeadBtn('c:trash-can', 'Never say this again');
    banBtn.classList.add('sp-find-bin');
    head.appendChild(traceBtn);
    head.appendChild(banBtn);
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.addEventListener('click', findClose);
    head.appendChild(x);
    box.appendChild(head);
    var why = make('div', 'sp-find-why', 'asking the station\u2026');
    box.appendChild(why);
    var facts = make('div', 'sp-find-facts');
    box.appendChild(facts);
    var trace = make('div', 'sp-find-trace');                    /* [#1241] */
    trace.id = 'spFindTrace';
    trace.hidden = true;
    box.appendChild(trace);
    traceBtn.addEventListener('click', function () {
      if (!trace.hidden) { trace.hidden = true; traceBtn.setAttribute('aria-expanded', 'false'); return; }
      traceBtn.setAttribute('aria-expanded', 'true');
      findTraceOpen(trace, q, '');
    });
    banBtn.addEventListener('click', function () { findBanAsk(back, trace, q); });
    var list = make('div', 'sp-find-list');
    box.appendChild(list);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) findClose(); });
    document.body.appendChild(back);
    Promise.resolve(api().get('/api/said/search?q=' + encodeURIComponent(q) + '&hours=48&limit=120')).then(function (d) {
      if (!d) { why.textContent = 'the station did not answer'; return; }
      why.textContent = d.why || d.say || '';
      /* [#1230] "They are saying that somewhere a system prompt is making it
         say that." Sometimes it is, and this names the line. Sometimes it is
         NOT - on "wanted us to explore" the verdict says "a persona or a
         prompt for that seat" and the tracer finds no persona and no prompt
         at all, only a line of code the tint rhymes. Either way the operator
         gets the answer instead of the guess, so a ONE VOICE or ONE ROAD
         verdict opens the pane by itself. */
      if (/^ONE (VOICE|ROAD)/.test(String(d.why || ''))) {
        traceBtn.setAttribute('aria-expanded', 'true');
        findTraceOpen(trace, q, String(d.why || ''), why);
      }
      var bits = [String(d.total || 0) + ' airing(s) in ' + (d.hours || 48) + 'h, ' + String(d.distinct || 0) + ' distinct line(s)'];
      (d.by_round || []).slice(0, 4).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      (d.by_who || []).slice(0, 3).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      facts.textContent = bits.join('  \u00b7  ');
      var dated = d.rows || [];
      /* #1117: a repeated row is a tally, not a line, so it has no id
         of its own. It borrows the first dated row that says the same
         words - the station's paperwork is per line, and any one of
         the airings is the same line. */
      function idFor(text) {
        var want = findNorm(text);
        if (!want) return '';
        var i, have;
        for (i = 0; i < dated.length; i += 1) {
          if (dated[i] && dated[i].id && findNorm(dated[i].text) === want) return String(dated[i].id);
        }
        /* The tally may quote a cut of the line; a prefix either way
           is still the same line. */
        for (i = 0; i < dated.length; i += 1) {
          have = dated[i] && dated[i].id ? findNorm(dated[i].text) : '';
          if (have && (have.indexOf(want) === 0 || want.indexOf(have) === 0)) return String(dated[i].id);
        }
        return '';
      }
      (d.repeated || []).slice(0, 5).forEach(function (t) {
        if (t.n < 2) return;
        var row = make('div', 'sp-find-rep');
        var line = make('div', 'sp-find-line');
        line.appendChild(findTri(row, idFor(t.text)));               /* #1117 */
        var main = make('span', 'sp-find-main');
        main.appendChild(make('b', null, '\u00d7' + t.n + ' '));
        main.appendChild(make('span', null, (t.who ? t.who + ': ' : '') + t.text));
        line.appendChild(main);
        row.appendChild(line);
        list.appendChild(row);
      });
      dated.forEach(function (r) {
        var row = make('div', 'sp-find-row');
        var line = make('div', 'sp-find-line');
        line.appendChild(findTri(row, r.id ? String(r.id) : ''));    /* #1117 */
        var main = make('div', 'sp-find-main');
        var ago = r.ago >= 3600 ? Math.round(r.ago / 3600) + 'h ago' : Math.round(r.ago / 60) + 'm ago';
        main.appendChild(make('span', 'sp-find-when', ago + ' \u00b7 ' + (r.who || '?') + ' \u00b7 ' + (r.round || r.kind || '')));
        main.appendChild(make('span', 'sp-find-text', r.text || ''));
        line.appendChild(main);
        row.appendChild(line);
        list.appendChild(row);
      });
      if (!(d.rows || []).length) list.appendChild(make('div', 'sp-find-row', 'not said on the air in the last two days'));
    }, function (err) {
      why.textContent = 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80);
    });
  }

  /* ---- #1241 / #1239 / #1230: where a phrase comes from, and the bin ---- */

  /* "I want an icon here for tracing a typed phrase through the prompts,
   *  the data crystal, the topics, the scripts, and find the source of where
   *  a scripted phrase is coming from. I need to be able to completely
   *  remove and delete and trace a phrase or saying from the dialogue and
   *  future scripting."  (#1241)
   * "I want the ability to have a trash can so that whenever I search for
   *  [a phrase] I'm able to delete [it] from the database and have it not
   *  said by the host anymore."  (#1239)
   * "They are saying that somewhere a system prompt is making it say that.
   *  I want the ability to make it stop doing that."  (#1230)
   *
   * The station does every bit of the work (GET /api/phrase/trace, POST and
   * DELETE /api/phrase/ban); this draws four layers in a fixed order, a tick
   * beside every source that can actually be removed, and a confirm sheet
   * that names the consequence in the station's own words before anything
   * is deleted. */

  var FIND_LAYER_ICON = {prompts: 'c:notebook', crystal: 'c:gem',
                         topics: 'c:chat', scripts: 'c:script'};

  function findHeadBtn(icon, title) {
    var b = make('button', 'sp-find-act', '');
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.setAttribute('aria-expanded', 'false');
    try {
      if (typeof root.pineIcon === 'function') b.innerHTML = root.pineIcon(icon, title);
    } catch (err) { /* the text below stands in */ }
    if (!b.innerHTML) b.textContent = title.slice(0, 1);
    return b;
  }

  function findTraceOpen(pane, q, verdict, whyNode) {
    pane.hidden = false;
    if (pane.pineTrace) { findTracePaint(pane, pane.pineTrace, verdict, whyNode); return; }
    if (pane.pineAsking) return;
    if (!api() || !api().get) { pane.textContent = 'no bridge to ask through'; return; }
    pane.textContent = 'asking the station where it is written<u2026>';
    pane.pineAsking = true;
    Promise.resolve(api().get('/api/phrase/trace?q=' + encodeURIComponent(q))).then(function (d) {
      pane.pineAsking = false;
      if (!d || d.ok === false) { pane.textContent = 'the station did not answer'; return; }
      pane.pineTrace = d;
      findTracePaint(pane, d, verdict, whyNode);
    }, function (err) {
      pane.pineAsking = false;
      pane.textContent = 'the station did not answer: '
        + String((err && err.message) || err).slice(0, 80);
    });
  }

  function findSourceLine(s) {
    var bits = [];
    if (s.what) bits.push(s.what);
    if (s.file) bits.push(s.file);
    if (s.line) bits.push('line ' + s.line);
    if (s.round) bits.push(s.round);
    if (s.count > 1) bits.push('<u00d7>' + s.count);
    return bits.join('  <u00b7>  ');
  }

  function findTracePaint(pane, d, verdict, whyNode) {
    pane.textContent = '';
    pane.appendChild(make('div', 'sp-find-trace-head',
      'Where it comes from  <u00b7>  ' + String(d.say || '')));

    /* THE CORRECTION. A phrase the tint RHYMED into being is written in no
       prompt and no persona, and every search of the prompts will keep
       finding nothing. Say so, and name the line the rhyme came off. */
    if (d.kin) {
      var kin = make('div', 'sp-find-kin', '');
      kin.appendChild(make('b', null, 'Not written anywhere. '));
      kin.appendChild(make('span', null,
        'No persona, prompt, crystal or topic contains this phrase. The rhyme '
        + 'pass made it out of <u201c>' + d.kin + '<u201d>, below <u2014> so the '
        + 'verdict above is pointing at a seat that never wrote it.'));
      pane.appendChild(kin);
    }

    var picked = pane.pinePicked || (pane.pinePicked = {});
    (d.layers || []).forEach(function (layer) {
      var box = make('div', 'sp-find-layer', '');
      var h = make('div', 'sp-find-layer-head', '');
      var mark = make('span', 'sp-find-layer-mark', '');
      try {
        if (typeof root.pineIcon === 'function') {
          mark.innerHTML = root.pineIcon(FIND_LAYER_ICON[layer.layer] || 'c:document', '');
        }
      } catch (err) { /* the label stands alone */ }
      h.appendChild(mark);
      h.appendChild(make('b', null, layer.label));
      h.appendChild(make('span', 'sp-find-layer-n',
        layer.count ? String(layer.count) + ' source(s)' : 'nothing'));
      h.appendChild(make('span', 'sp-find-layer-why', layer.blurb || ''));
      box.appendChild(h);
      (layer.sources || []).forEach(function (s) {
        var row = make('div', 'sp-find-src', '');
        row.dataset.src = s.id;
        var can = (s.kill === 'strip' || s.kill === 'drop' || s.kill === 'deactivate');
        var tick = make('button', 'sp-find-tick', '');
        tick.type = 'button';
        tick.setAttribute('role', 'checkbox');
        tick.setAttribute('aria-checked', 'false');
        tick.title = can ? ('Remove this too: ' + (s.kill_label || ''))
                         : (s.kill_label || 'nothing here can be removed');
        tick.disabled = !can;
        function drawTick() {
          var on = !!picked[s.id];
          tick.setAttribute('aria-checked', on ? 'true' : 'false');
          try {
            if (typeof root.pineIcon === 'function') {
              tick.innerHTML = root.pineIcon(on ? 'c:checkbox--checked' : 'c:checkbox', '');
            }
          } catch (err) { /* fall through */ }
          if (!tick.innerHTML) tick.textContent = on ? '[x]' : '[ ]';
        }
        drawTick();
        tick.addEventListener('click', function () {
          if (!can) return;
          if (picked[s.id]) delete picked[s.id]; else picked[s.id] = true;
          drawTick();
        });
        row.appendChild(tick);
        var body = make('div', 'sp-find-src-body', '');
        body.appendChild(make('div', 'sp-find-src-name', s.label || s.store));
        body.appendChild(make('div', 'sp-find-src-where', findSourceLine(s)));
        body.appendChild(make('div', 'sp-find-src-snip', s.snippet || ''));
        if (s.why) body.appendChild(make('div', 'sp-find-src-why', s.why));
        if (!can && s.kill_label) body.appendChild(make('div', 'sp-find-src-why', s.kill_label));
        row.appendChild(body);
        box.appendChild(row);
      });
      if (!(layer.sources || []).length) {
        box.appendChild(make('div', 'sp-find-src sp-find-src-none',
          'nothing in this layer says it'));
      }
      pane.appendChild(box);
    });

    /* #1230: turn the verdict itself into the link the operator asked for. */
    if (whyNode && /^ONE (VOICE|ROAD)/.test(String(verdict || ''))) {
      var src = d.verdict_source;
      whyNode.textContent = String(verdict || '');
      var jump = make('button', 'sp-find-link', '');
      if (src) {
        jump.textContent = '<u2192> ' + (src.label || src.store)
          + (src.file ? ' (' + src.file + (src.line ? ':' + src.line : '') + ')' : '');
        jump.title = 'Show the exact line the tracer found';
        jump.addEventListener('click', function () {
          pane.hidden = false;
          var node = pane.querySelector('[data-src="' + src.id + '"]');
          if (node) {
            node.classList.add('lit');
            try { node.scrollIntoView({block: 'center'}); } catch (err) { /* no view */ }
          }
        });
      } else {
        jump.textContent = d.kin
          ? '<u2192> no prompt says it: the tint rhymes it out of <u201c>' + d.kin + '<u201d>'
          : '<u2192> no prompt, persona, crystal or topic says it';
        jump.title = 'What the tracer actually found';
        jump.addEventListener('click', function () { pane.hidden = false; });
      }
      whyNode.appendChild(jump);
    }
  }

  /* ---- #1239: the trash can, and the sheet that names the cost ---- */

  function findBanAsk(back, pane, q) {
    if (el('spFindBan')) return;
    var wrap = make('div', 'sp-find-confirm-back');
    wrap.id = 'spFindBan';
    var sheet = make('div', 'sp-find-confirm');
    var picked = Object.keys((pane && pane.pinePicked) || {});
    var d = (pane && pane.pineTrace) || null;
    sheet.appendChild(make('div', 'sp-find-confirm-head',
      'Never say <u201c>' + q + '<u201d> again'));
    var body = make('div', 'sp-find-confirm-body', '');
    if (d) {
      body.appendChild(make('div', null, d.confirm || ''));
    } else {
      body.appendChild(make('div', null,
        'The station has not been asked where it comes from yet <u2014> the ban '
        + 'still holds, and the trace will show what it took.'));
    }
    var says = make('ul', 'sp-find-confirm-list', '');
    [['it is blocked in the writing prompt, stripped out at the mouth, and '
      + 'refused on the rhyme pass’s way out'],
     ['every prepared round that says it is retired to the retirement desk, '
      + 'reason <u201c>phrase banned<u201d>, and can never go on air'
      + (d ? ' <u2014> ' + String(d.rounds || 0) + ' round(s) right now' : '')],
     ['every gold bar that says it is burnt'
      + (d ? ' <u2014> ' + String(d.bars || 0) + ' bar(s) right now' : '')],
     [picked.length
       ? String(picked.length) + ' ticked source(s) are removed from their desk'
       : 'nothing written in a persona, prompt, crystal or topic is deleted '
         + 'unless you tick it in the pane'],
     ['it is written in the judgment book, and the trash can lifts it again']
    ].forEach(function (t) { says.appendChild(make('li', null, t[0])); });
    body.appendChild(says);
    sheet.appendChild(body);
    var row = make('div', 'sp-find-confirm-row', '');
    var no = make('button', 'sp-find-confirm-no', 'Cancel');
    no.type = 'button';
    no.addEventListener('click', function () { wrap.remove(); });
    var yes = make('button', 'sp-find-confirm-yes',
      (d && d.banned) ? 'Let it be said again' : 'Never say it again');
    yes.type = 'button';
    yes.addEventListener('click', function () {
      yes.disabled = true;
      findBanDo(wrap, back, q, picked, !!(d && d.banned));
    });
    row.appendChild(no);
    row.appendChild(yes);
    sheet.appendChild(row);
    wrap.appendChild(sheet);
    wrap.addEventListener('click', function (ev) { if (ev.target === wrap) wrap.remove(); });
    document.body.appendChild(wrap);
    /* A confirm sheet is a report surface: the radio ducks while it is up,
       and the hold dies with the node (standing rule, PineDuck). */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-find-ban', root.PineDuck.REPORT, wrap);
    }
  }

  function findBanDo(wrap, back, q, picked, lift) {
    var note = make('div', 'sp-find-confirm-note', 'telling the station<u2026>');
    wrap.firstChild.appendChild(note);
    var call;
    if (lift && api() && api().del) {
      call = api().del('/api/phrase/ban?q=' + encodeURIComponent(q));
    } else if (!api() || !api().post) {
      note.textContent = 'no bridge to the station';
      return;
    } else {
      call = api().post('/api/phrase/ban',
        lift ? {phrase: q, lift: true}
             : {phrase: q, scope: 'everywhere', sources: picked,
                reason: 'banned from the word search on the script view'});
    }
    Promise.resolve(call).then(function (got) {
      note.textContent = (got && got.say) || 'done';
      try { say((got && got.say) || 'done'); } catch (err) { /* no voice line */ }
      var trace = el('spFindTrace');
      if (trace) { trace.pineTrace = null; trace.pinePicked = {}; }
      root.setTimeout(function () {
        wrap.remove();
        if (trace && !trace.hidden) findTraceOpen(trace, q, '');
      }, 1400);
    }, function (err) {
      note.textContent = 'the station refused: '
        + String((err && err.message) || err).slice(0, 120);
    });
  }

  /* ---- #1117: the triangle at the front of every row ------------- */

  /* "I want an expandable triangle at the beginning of all of these
   *  that allows me to see what property set this and allow me to
   *  change or manage those or adjust them in the system prompt or see
   *  what systems contributed to making them the way that they are,
   *  whatever I search for them."
   *
   * The station answers GET /api/said/why/{id} with three lists: what
   * SET the line (only the properties in force), the per-road system
   * prompt (saved back through POST /api/said/prompt, in force from
   * the next round), and what contributed, on or off. This draws them
   * under the row and nothing more. The answer is cached on the row
   * node, so a second tap costs the station nothing. */
  function findNorm(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function findTri(row, id) {
    var tri = make('button', 'sp-find-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    try {
      if (typeof root.pineIcon === 'function') {
        tri.innerHTML = root.pineIcon('c:caret--right', 'What set this line');
      }
    } catch (err) { /* the text below stands in */ }
    if (!tri.innerHTML) tri.textContent = '>';
    if (!id) {
      tri.disabled = true;
      tri.title = 'no line id to ask about';
      return tri;
    }
    tri.title = 'What set this line, the system prompt for its road, and what contributed';
    tri.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var open = tri.getAttribute('aria-expanded') === 'true';
      tri.setAttribute('aria-expanded', open ? 'false' : 'true');
      row.classList.toggle('open', !open);
      var panel = row.querySelector('.sp-find-why-panel');
      if (open) { if (panel) panel.hidden = true; return; }
      if (!panel) {
        panel = make('div', 'sp-find-why-panel', 'asking the station…');
        row.appendChild(panel);
      }
      panel.hidden = false;
      if (row.pineWhy || row.pineWhyAsking) return;   /* held, or in flight */
      if (!api() || !api().get) { panel.textContent = 'no bridge to ask through'; return; }
      row.pineWhyAsking = true;
      Promise.resolve(api().get('/api/said/why/' + encodeURIComponent(id))).then(function (d) {
        row.pineWhyAsking = false;
        if (!d || d.ok === false) {
          panel.textContent = 'the station did not answer'
            + (d && d.say ? ': ' + String(d.say).slice(0, 120) : '');
          return;
        }
        row.pineWhy = d;
        findWhyPaint(panel, d);
      }, function (err) {
        row.pineWhyAsking = false;
        panel.textContent = 'the station did not answer: '
          + String((err && err.message) || err).slice(0, 80);
      });
    });
    return tri;
  }

  function findWhyPaint(panel, d) {
    panel.replaceChildren();
    var i;

    /* (1) what set this - the properties in force, name -> value, and
       the desk each one lives on in a dim aside. */
    panel.appendChild(make('div', 'sp-why-h', 'what set this'));
    var props = d.properties || [];
    if (!props.length) {
      panel.appendChild(make('div', 'sp-why-dim', 'nothing on record set this line'));
    } else {
      var dl = make('dl', 'sp-why-dl');
      for (i = 0; i < props.length; i += 1) {
        var p = props[i] || {};
        dl.appendChild(make('dt', null, String(p.name || '')));
        var dd = make('dd', null, (p.value === undefined || p.value === null) ? '' : String(p.value));
        if (p.where) {
          dd.appendChild(document.createTextNode(' '));
          dd.appendChild(make('i', null, String(p.where)));
        }
        dl.appendChild(dd);
      }
      panel.appendChild(dl);
    }

    /* (2) the system prompt for this road - folded, because it is the
       long one; editable where the station says so. */
    var prompt = d.prompt || {};
    var det = make('details', 'sp-why-prompt');
    det.appendChild(make('summary', null, 'the system prompt for this road'
      + (prompt.kind ? ' (' + String(prompt.kind) + ')' : '')));
    var ta = make('textarea', 'sp-why-ta', '');
    ta.rows = 6;
    ta.spellcheck = false;
    ta.value = String(prompt.text || '');
    ta.readOnly = !prompt.editable;
    det.appendChild(ta);
    if (prompt.editable) {
      var saveRow = make('div', 'sp-why-save');
      var save = make('button', 'sp-btn sp-why-savebtn', 'Save to the prompt book');
      save.type = 'button';
      var said = make('span', 'sp-why-dim', '');
      save.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (!api() || !api().post) { said.textContent = 'no bridge to save through'; return; }
        save.disabled = true;
        said.textContent = 'saving…';
        Promise.resolve(api().post('/api/said/prompt', {kind: prompt.kind, text: ta.value})).then(function (got) {
          save.disabled = false;
          if (got && got.ok === false) {
            said.textContent = 'not saved' + (got.say ? ': ' + String(got.say).slice(0, 120) : '');
            return;
          }
          said.textContent = String((got && got.say)
            || 'saved - it takes effect on the next round');
        }, function (err) {
          save.disabled = false;
          said.textContent = 'not saved: ' + String((err && err.message) || err).slice(0, 80);
        });
      });
      saveRow.appendChild(save);
      saveRow.appendChild(said);
      det.appendChild(saveRow);
    } else {
      det.appendChild(make('div', 'sp-why-dim',
        String(prompt.why || prompt.say || 'this prompt cannot be changed from here')
        + (prompt.where ? ' - it lives in ' + String(prompt.where) : '')));
    }
    panel.appendChild(det);

    /* (3) what contributed - each system on or off, with its note;
       the ones that stood aside are dimmed, not hidden, because "the
       crystal was off" is itself part of the answer. */
    panel.appendChild(make('div', 'sp-why-h', 'what contributed'));
    var systems = d.systems || [];
    if (!systems.length) {
      panel.appendChild(make('div', 'sp-why-dim', 'no system is on record for this line'));
    } else {
      var ul = make('ul', 'sp-why-sys');
      for (i = 0; i < systems.length; i += 1) {
        var s = systems[i] || {};
        var li = make('li', s.on ? 'on' : 'off');
        li.appendChild(make('b', null, String(s.name || '')));
        li.appendChild(make('span', 'sp-why-onoff', s.on ? 'on' : 'off'));
        if (s.note) li.appendChild(make('span', 'sp-why-note', String(s.note)));
        ul.appendChild(li);
      }
      panel.appendChild(ul);
    }

    /* (4) the honesty line: without the booth's ring the properties
       above are the air log's word alone. */
    if (d.provenance_ok === false) {
      panel.appendChild(make('div', 'sp-why-dim sp-why-noprov',
        'the booth no longer holds this line’s paperwork - only the air log speaks for it'));
    }
    if (d.say) panel.appendChild(make('div', 'sp-why-say', String(d.say)));
  }

  /* ---- #1115: the report of a wrong highlight -------------------- */

  /* Everything is gathered BEFORE the picture is asked for, so the
   * numbers describe the moment of the tap and not the moment the
   * chrome got round to it. Every reading is guarded: a report about
   * a fault must not be the thing the fault breaks. */
  var reportTurn = 0;

  function jsonSafe(v) {
    try { return JSON.parse(JSON.stringify(v === undefined ? null : v)); }
    catch (err) { try { return String(v); } catch (e2) { return null; } }
  }

  function attempt(fn) {
    try { return jsonSafe(fn()); }
    catch (err) { return {error: String((err && err.message) || err).slice(0, 200)}; }
  }

  /* Passive rolling diagnostics: the previous minute of observed changes,
   * full line identities and audio coordinates. The tap submits immediately;
   * a screenshot and ten seconds of subsequent evidence finish the report.
   * Recording never scrolls the view or changes playback. */
  /* Two samples a second preserves a useful pre-incident history without
     forcing layout on a thousand-row screenplay four times a second. */
  var MOTION_MS = 500;
  var motionTimer = 0;
  var diagnosticRecorder = null;
  var diagnosticNodes = [];
  var diagnosticIndices = new Map();
  var diagnosticLines = Object.create(null);
  var diagnosticRevision = '';
  var diagnosticSnapshot = null;
  var diagnosticHiddenCount = 0;
  var diagnosticTransitionCount = 0;
  function recorder() {
    if (!diagnosticRecorder && root.PineScriptDiagnostics) diagnosticRecorder = root.PineScriptDiagnostics.createRecorder();
    return diagnosticRecorder;
  }
  function diagnosticDocument(box) {
    diagnosticNodes = scriptOrder.slice();
    diagnosticIndices = new Map();
    diagnosticLines = Object.create(null);
    diagnosticHiddenCount = 0;
    diagnosticTransitionCount = 0;
    diagnosticNodes.forEach(function (n, i) {
      diagnosticIndices.set(n, i);
      if (n.pineItem && n.pineItem.line) diagnosticLines[String(n.pineItem.line)] = {item: n.pineItem, index: i};
      if (n.hidden || n.parentNode !== box) diagnosticHiddenCount += 1;
      if (n.classList.contains('sp-fx')) diagnosticTransitionCount += 1;
    });
    if (root.PineScriptDiagnostics) diagnosticRevision = root.PineScriptDiagnostics.revision(elements);
  }

  /* The references, resolved against the admitted map. `available: false`
     with a reason is a legitimate answer and the only honest one when the
     station has not been patched to carry the field yet. */
  function admissionReferences() {
    var out = {available: false, why: 'the station is not sending an admitted cue map',
      generation: null, mode: '', reader_position: null,
      playback_occurrence_id: null, position: null, media: null,
      script_revision: null, performer_session: null, assembly_id: null,
      cue_map_revision: null, take_id: null, audio_hash: null,
      accepted_cuts: null, origin: null};
    if (!admitMap || !admitMap.ok) return out;
    out.generation = admitMap.generation;
    out.mode = admitMap.mode;
    out.reader_position = admitMap.reader;
    var want = (lastGood && lastGood.occurrence_id)
      || (admitMap.current && admitMap.current.occurrence_id) || '';
    var found = null;
    for (var i = 0; i < admitMap.order.length; i += 1) {
      if (admitMap.order[i].occurrence_id === want) { found = admitMap.order[i]; break; }
    }
    if (!found) {
      out.why = want
        ? 'the admitted map no longer carries occurrence ' + want
        : 'no occurrence has been dispatched yet';
      return out;
    }
    out.available = true;
    out.why = '';
    out.playback_occurrence_id = found.occurrence_id;
    out.position = found.position;
    out.media = found.media;
    out.origin = found.origin;
    /* Absent, not blank: an empty string from the server means the record
       exists and the field is unset, and saying `null` says exactly that. */
    out.script_revision = found.script_revision || null;
    out.performer_session = found.performer_session || null;
    out.assembly_id = found.assembly_id || null;
    out.cue_map_revision = found.cue_map_revision || null;
    out.take_id = found.take_id || null;
    out.audio_hash = found.hash || null;
    var cuts = [];
    for (var c = 0; c < found.cues.length; c += 1) {
      if (found.cues[c].cut_id) cuts.push(found.cues[c].cut_id);
    }
    out.accepted_cuts = cuts.length ? cuts.slice(0, 24) : null;
    return out;
  }

  function sampleMotion() {
    var pane = el('spScript');
    var rec = recorder();
    if (!pane || !rec) return;
    var lit = pane.querySelector('.sp-el.sp-now');
    var feedMark = !!(lit && lit.classList.contains('sp-feed-now'));
    var idx = diagnosticIndices.has(lit) ? diagnosticIndices.get(lit) : -1;
    /* [#1189] THE RESOLVER'S OWN ANSWER, not a second computation. The
       recorder used to call activeRow() itself; the highlight was placed
       by another timer from another call. */
    var decision = lastDecision || {};
    var audio = root.PineScriptDiagnostics.readAudio(bridgeHead(), soundingPlayer(), streamAt());
    /* [#1282] THE MARK AND ITS EVIDENCE ARE ONE READ.

       readAudio() above is a SECOND read of the player, milliseconds after
       the one inside evidence() that placed the mark. At the end of a clip
       the element ends between them, streamAt() falls back to the station
       clock, and the sample was written down as `mark: "air"` beside
       `source: "estimated"` - a fault the view never committed. Every
       occurrence of "marked ON AIR while its position was estimated" in the
       captures is exactly that: one 500ms sample, road `file-tail`, which is
       the last instant of the file. Measured at that sample: the resolver
       read 32.41s off the player, the clock said 29.38s.

       The decision already carries the evidence that placed it - source,
       file, offset and the ms it was read. When the fresh read has nothing
       and the decision was read off a player, that is what the sample
       records. An estimate is never written beside a placed mark, and
       selectMappings() below gets a real filename again, so the capture
       keeps the cue rows of the clip that was sounding. */
    if ((audio.source === 'estimated' || audio.source === 'unavailable')
        && (decision.source === 'bridge' || decision.source === 'local')
        && decision.t !== null && decision.t !== undefined && isFinite(Number(decision.t))) {
      audio = {source: String(decision.source), file: String(decision.file || ''),
        position_s: Number(decision.t),
        observed_at_ms: isFinite(Number(decision.at_ms)) ? Number(decision.at_ms) : null,
        from_decision: true, player_state_available: false, volume: null,
        muted: null, ready_state: null, network_state: null, buffered_end_s: null};
    }
    var active = decision.mark === 'air' ? {id: String(decision.line_id || '')} : {};
    var feed = [];
    try { feed = root.PineStationFeed.rows() || []; } catch (e) { /* no feed */ }
    var records = [], nearby = [], mapping = [], byId = Object.create(null);
    feed.forEach(function (r) { if (r.id) byId[String(r.id)] = r; });
    var rect = pane.getBoundingClientRect(), visible = -1;
    var knownActive = diagnosticLines[String(active.id || '')];
    if (idx < 0 && !knownActive && document.elementFromPoint) {
      var hit = document.elementFromPoint(rect.left + Math.min(24, rect.width / 2), rect.top + 2);
      var visibleNode = hit && hit.closest ? hit.closest('.sp-el') : null;
      visible = diagnosticIndices.has(visibleNode) ? diagnosticIndices.get(visibleNode) : -1;
    }
    var contextAt = root.PineScriptDiagnostics.contextIndex(idx, knownActive ? knownActive.index : -1, visible, diagnosticNodes.length);
    var from = contextAt < 0 ? 0 : Math.max(0, contextAt - 20);
    var to = contextAt < 0 ? -1 : Math.min(diagnosticNodes.length - 1, contextAt + 10);
    for (var i = from; i <= to; i += 1) {
      var n = diagnosticNodes[i], item = n.pineItem || {};
      var id = String(item.line || (item.id ? 'element:' + item.id : ''));
      nearby.push({id: id, element_id: String(item.id || ''), index: i, block: item.block, ord: item.ord});
      if (id) {
        var source = byId[id] || {};
        records.push({id: id, element_id: item.id, block: item.block, ord: item.ord,
          kind: item.type, who: source.who || source.name || '', text: item.text,
          media: rowFile(source), from_s: rowFrom(source), until_s: rowUntil(source), document_index: i,
          sfx: String(source.sfx || ''), url: String(source.url || item.clip || item.url || ''),   /* [#1189] */
          aired: String(source.aired || item.aired || '')});
      }
    }
    // Keep a small cue neighborhood and both claimed identities. Copying the
    // whole file can evict the very rows needed to explain a long burst.
    var candidates = root.PineScriptDiagnostics.selectMappings(feed, audio, String(active.id || ''), lit ? String(lit.dataset.line || '') : '');
    candidates.rows.forEach(function (r) {
        mapping.push(String(r.id || ''));
        if (!records.some(function (held) { return held.id === String(r.id || ''); })) {
          var known = diagnosticLines[String(r.id || '')] || {}, item = known.item || {};
          records.push({id: r.id, kind: r.kind, who: r.who || r.name, text: r.text,
            media: rowFile(r), from_s: rowFrom(r), until_s: rowUntil(r),
            sfx: String(r.sfx || ''), url: String(r.url || ''), aired: String(r.aired || ''),   /* [#1189] */
            element_id: item.id, block: item.block, ord: item.ord, document_index: known.index});
        }
    });
    var top = lit ? Math.round(lit.getBoundingClientRect().top - rect.top) : null;
    var hiddenCount = diagnosticHiddenCount;
    var transitionCount = diagnosticTransitionCount;
    diagnosticSnapshot = {
      recorder_version: 2, capture_source: 'script-page',
      highlight_id: lit ? String(lit.dataset.line || '') : '', active_id: String(active.id || ''),
      highlight_basis: feedMark ? 'feed-voice' : String(decision.road || 'none'),
      document_revision: diagnosticRevision, script_age_ms: fetchedAt ? Date.now() - fetchedAt : null,
      speaking_id: String((speakingNow && speakingNow.id) || ''), audio: audio,
      nearby: nearby, context_index: contextAt,
      context_source: idx >= 0 ? 'highlight' : knownActive ? 'active' : visible >= 0 ? 'viewport' : 'unavailable',
      mapping_rows: mapping, mapping_rows_total: candidates.total,
      mapping_rows_omitted: candidates.omitted, matching_file_rows_total: candidates.matching_file_total,
      stream: liveStream ? {at: liveStream.at, length: liveStream.length, row_count: (liveStream.rows || []).length,
        rows: (liveStream.rows || []).filter(function (r) { return String(r.id || '') === String(active.id || '') || String(r.id || '') === nowLineId; }).map(function (r) { return {id: r.id, from: r.from, until: r.until}; })} : null,
      viewport: {scroll_top_px: Math.round(pane.scrollTop), height_px: pane.clientHeight, width_px: pane.clientWidth, content_height_px: pane.scrollHeight, lit_top_px: top},
      layout: {live_segment: String(liveSeg || ''),
        highlighted_segment: lit ? String(lit.dataset.seg || '') : '',
        nodes_total: diagnosticNodes.length, nodes_hidden: hiddenCount,
        nodes_transitioning: transitionCount,
        segments_folded: Object.keys(folded).filter(function (key) {
          return folded[key] && key !== liveSeg;
        }).length},
      paused: stationPaused, follow: follow, visibility: String(document.visibilityState || ''),
      /* THE INCIDENT REFERENCES section 5 of the recording note asks
         for: script revision, performer session, accepted cut, assembly
         and playback occurrence. Every one of them is taken from what the
         STATION actually returned. A reference the station does not carry
         is absent here; it is never filled in with something plausible. */
      admission: admissionReferences(),
      sync: {state: syncState, why: syncWhy, since_ms: syncSince,
        motion: syncRing.slice(-60),
        last_trustworthy: lastGood ? {line_id: lastGood.line_id,
          occurrence_id: lastGood.occurrence_id, position: lastGood.position,
          media: lastGood.media, at_ms: lastGood.at} : null},
      scroll: {owner: scrollOwner, at_ms: scrollAt, moves: scrollLog.slice(-12)},
      /* [#1189] HOW THE MARK WAS PLACED, so the next capture explains
         itself: the decision that stands, the ring of decisions before it,
         what was expected and what was carried, and the station's verdict. */
      resolver: resolverSnapshot(),
      expected_id: String(decision.expected_id || ''),
      carried_id: String(decision.carried_id || ''),
      playout: playoutNow ? {verdict: playoutNow.verdict, occurrence_id: playoutNow.occurrence_id,
        line_id: playoutNow.line_id, block: playoutNow.block, ord: playoutNow.ord,
        file: playoutNow.file, offset_s: playoutNow.offset_s, at_ms: playoutNow.at_ms,
        agrees: playoutAgrees()} : null,
      errors: caught.slice(-6)
    };
    rec.observe({at_ms: Date.now(), highlight_id: diagnosticSnapshot.highlight_id, active_id: diagnosticSnapshot.active_id,
      document_revision: diagnosticRevision, element_index: idx, block: lit && lit.dataset.block,
      ord: lit && lit.dataset.ord, scroll_top_px: Math.round(pane.scrollTop), lit_top_px: top,
      audio: audio, follow: follow, paused: stationPaused, snapshot: diagnosticSnapshot,
      mark: feedMark ? 'feed-inferred' : String(decision.mark || ''),
      road: feedMark ? 'feed-voice' : String(decision.road || ''),
      sync: String(decision.sync || ''), expected_id: String(decision.expected_id || ''),
      carried_id: String(decision.carried_id || ''),
      /* #1277: enough layout provenance to distinguish a server reindex from
         restore, fold and follow moving the viewport after that reindex. */
      scroll_owner: String(scrollOwner || ''), scroll_owner_at_ms: Number(scrollAt || 0),
      live_segment: String(liveSeg || ''),
      highlighted_segment: lit ? String(lit.dataset.seg || '') : '',
      nodes_transitioning: transitionCount}, records);
  }
  var reportKind = 'report';
  function ensureCaution() {
    var pane = el('spScript');
    if (!pane) return;
    var wrap = document.getElementById('spCautionWrap');
    if (wrap && wrap.parentNode === pane && pane.firstChild === wrap) return;
    if (!wrap) {
      wrap = make('div', 'sp-caution-wrap', '');
      wrap.id = 'spCautionWrap';
      var b = make('button', 'sp-caution', '');
      b.type = 'button';
      b.title = 'Report a script jump: keep the previous minute, this moment, and the next 10 seconds in the Pine inbox';
      b.setAttribute('aria-label', 'Report the script as erratic');
      try { if (typeof root.pineIcon === 'function') b.innerHTML = root.pineIcon('c:warning--alt', 'Report the script as erratic'); } catch (e) { /* text */ }
      if (!b.innerHTML) b.textContent = '!';
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (b.pineHeld) return;   /* 2026-09-14: the hold opened the reason sheet */
        reportKind = 'caution';
        b.classList.add('sp-firing');
        try { reportFire(b); } finally { setTimeout(function () { reportKind = 'report'; }, 100); }
      });
      /* 2026-09-14: HOLD IT (or right-click it) to say why first -
         the reason sheet, reasonOpen(). A tap still files at once. */
      holdOpen(b, function () { reasonOpen(b); });
      wrap.appendChild(b);
    }
    pane.insertBefore(wrap, pane.firstChild);
  }

  function reportGather(phase, incident, since) {
    sampleMotion();
    var rec = recorder();
    if (!rec) throw new Error('script diagnostics did not load');
    return rec.capture(Date.now(), phase || 'tap', incident || '', since, diagnosticSnapshot);
  }

  /* The picture. On the desktop the chrome can take one
     (pineDesktop.shotView); on the tablet the kiosk may offer
     screenshot(); either may be missing, slow or broken, and none of
     that may hold the report - five seconds and it goes without. */
  function reportImage() {
    var bridge = api(), ask = null, source = 'unavailable', requested = Date.now();
    try {
      if (bridge && typeof bridge.shotView === 'function') { source = 'shotView'; ask = bridge.shotView(); }
      else if (bridge && typeof bridge.screenshot === 'function') { source = 'screenshot'; ask = bridge.screenshot(); }
    } catch (err) { return Promise.resolve({image: null, screenshot_source: source, screenshot_at_ms: requested, screenshot_error: String(err.message || err).slice(0, 160)}); }
    if (!ask) return Promise.resolve({image: null, screenshot_source: source, screenshot_at_ms: requested, screenshot_error: 'screenshot unavailable'});
    return new Promise(function (resolve) {
      var settled = false;
      function finish(image, error) {
        if (settled) return;
        settled = true; clearTimeout(late);
        resolve({image: image, screenshot_source: source, screenshot_at_ms: Date.now(),
          screenshot_requested_at_ms: requested, screenshot_error: error || null});
      }
      var late = setTimeout(function () { finish(null, 'screenshot timed out after 5 seconds'); }, 5000);
      Promise.resolve(ask).then(function (got) {
        var url = (got && typeof got === 'object') ? (got.dataUrl || got.data_url || got.image || got.png || '') : got;
        if (typeof url === 'string' && /^data:image\//.test(url)) { finish(url); return; }
        if (typeof url === 'string' && /^[A-Za-z0-9+\/=\s]+$/.test(url) && url.length > 64) {
          finish('data:image/png;base64,' + url.replace(/\s+/g, '')); return;
        }
        finish(null, 'screenshot returned no image');
      }, function (err) { finish(null, String((err && err.message) || err).slice(0, 160)); });
    });
  }

  /* THE PHOTOGRAPHY EFFECT. A white flash over the whole view, the
     word "captured" on the strip. It fires AFTER the picture has been
     asked for - a real shutter is heard after the exposure, and a
     flash painted before the chrome grabbed the frame would put a
     white sheet in the report - with a 400 ms cap so a slow capture
     never leaves the tap feeling dead. */
  function reportShutter() {
    var into = host || document.body;
    var flash = make('div', 'sp-shutter');
    into.appendChild(flash);
    setTimeout(function () { try { flash.remove(); } catch (err) { /* gone */ } }, 520);
  }

  /* 2026-09-14: `reason` is the operator's own why, from the reason
     sheet (a hold on the caution button); a plain tap files without
     one. The station stores it and leads the inbox summary with it. */
  var REPORT_PENDING_KEY = 'pine-script-report-finishes-v2';
  function pendingReports() {
    try { return JSON.parse(root.localStorage.getItem(REPORT_PENDING_KEY) || '[]').slice(-3); }
    catch (e) { return []; }
  }
  function keepPending(name, body) {
    try {
      var saved = pendingReports().filter(function (r) { return r.name !== name; });
      if (body) {
        var small = Object.assign({}, body, {image: null});
        if (body.image) small.screenshot_error = 'image was not retained for retry; original upload failed';
        saved.push({name: name, body: small});
      }
      root.localStorage.setItem(REPORT_PENDING_KEY, JSON.stringify(saved.slice(-3)));
    } catch (e) { caughtNote('report-persistence', e); }
  }
  function finishReport(name, body) {
    keepPending(name, body);
    return Promise.resolve(api().post('/api/script/report/' + encodeURIComponent(name) + '/finish', body)).then(function (got) {
      if (got && got.ok === false) throw new Error(got.say || 'the station refused the attachment');
      keepPending(name, null);
      return got;
    });
  }
  function retryReports() {
    pendingReports().forEach(function (held) {
      if (!/^script_[A-Za-z0-9_-]+\.md$/.test(held.name || '')) return;
      finishReport(held.name, held.body).catch(function (err) { caughtNote('report-retry', err); });
    });
  }
  function reportFire(btn, reason) {
    var mine = (reportTurn += 1), tapped = Date.now();
    if (!api() || !api().post) { say('no bridge to file the report through'); return; }
    btn.classList.add('sp-firing');
    function done(text, bad) {
      if (mine !== reportTurn) return;
      btn.classList.remove('sp-firing'); btn.classList.toggle('sp-fired-bad', !!bad); say(text);
      setTimeout(function () { btn.classList.remove('sp-fired-bad'); }, 2600);
    }
    var incident = (root.crypto && root.crypto.randomUUID) ? root.crypto.randomUUID()
      : ('script-' + tapped + '-' + Math.random().toString(16).slice(2));
    var view;
    try { view = reportGather('tap', incident); }
    catch (err) { done('not filed: ' + String(err.message || err).slice(0, 80), true); return; }
    tapped = view.captured_at_ms;
    // Submit the tap immediately. Screenshot latency cannot move the server's
    // initial observation or erase the evidence already collected.
    var initial;
    try { initial = Promise.resolve(api().post('/api/script/report', {view: view,
      reason: reason ? String(reason).slice(0, 1200) : null, incident_id: incident})); }
    catch (err) { done('not filed: ' + String(err.message || err).slice(0, 80), true); return; }
    var shot = reportImage(), flashed = false;
    function flash() { if (flashed) return; flashed = true; reportShutter(); }
    setTimeout(flash, 400); shot.then(flash, flash);
    var after = new Promise(function (resolve) {
      setTimeout(function () {
        try { resolve(reportGather('post', incident, tapped + 1)); }
        catch (err) { resolve({schema_version: 2, phase: 'post', incident_id: incident,
          captured_at_ms: Date.now(), events: [], rows: {}, snapshot: {errors: [{at: Date.now(),
            kind: 'post-capture', msg: String(err.message || err).slice(0, 200)}]}}); }
      }, 10000);
    });
    initial = initial.then(function (got) {
      if (!got || got.ok === false || !got.file) throw new Error((got && got.say) || 'the report was not acknowledged');
      if (mine === reportTurn) say('filed as #' + got.id + ' - capturing 10 seconds after the tap');
      return got;
    });
    Promise.all([initial, after, shot]).then(function (all) {
      var got = all[0], name = String(got.file).split('/').pop();
      var body = Object.assign({view: all[1], incident_id: incident}, all[2]);
      return finishReport(name, body).then(function () {
        done('filed as #' + got.id + ' - capture complete' + (body.screenshot_error ? ' (without a picture)' : ''));
      }, function (err) { done('report #' + got.id + ' kept; attachment pending: ' + String(err.message || err).slice(0, 65), true); });
    }).catch(function (err) { done('not filed: ' + String((err && err.message) || err).slice(0, 80), true); });
  }

  function fireVideo(btn) {
    var mine = (reelTurn += 1);
    function done(text, bad) {
      if (mine !== reelTurn) return;  /* a newer tap owns the screen */
      btn.classList.remove('sp-firing');
      btn.classList.toggle('sp-fired-bad', !!bad);
      say(text);
      setTimeout(function () { btn.classList.remove('sp-fired-bad'); }, 2600);
    }
    /* #1306: the CUE road, not the fill road. dj_sting's path cost
       4.6-5.7s warm, none of it the pick - the chat row, the history
       write, the length probe and the whole satellite/announce
       decision a video never uses. This rings the clip and hands it
       straight back, and the set cuts to it here rather than waiting
       out its own 2.5s poll. Rapid taps therefore cycle. */
    api().post('/api/sfx/video/cue', {who: 'operator'}).then(function (got) {
      var clip = got && got.clip;
      if (!clip) {
        done(String((got && got.say) || 'no clip'), true);
        /* #1361b: A MISS IS A QUESTION, NOT A VERDICT. Four different
           faults have printed the same four words on this strip, and
           only one of them is cured by tapping again. The doctor
           names which one this is and puts the cure under a thumb. */
        try {
          if (root.PineClipDoctor) root.PineClipDoctor.open(String((got && got.say) || ''));
        } catch (err) { /* the strip already said it */ }
        return;
      }
      /* #1311b: an answer that has been overtaken is dropped rather
         than cutting the picture backwards. */
      if (mine !== reelTurn) return;
      try {
        if (root.PineSfxTv && root.PineSfxTv.cut) root.PineSfxTv.cut(clip);
      } catch (err) { /* the clip is in the ring either way */ }
      /* Not an error if the set is not on this surface - the clip is in
         the ring either way and whatever is watching will show it. */
      done(String(clip.sting || 'on the set'));
    }, function (err) {
      done(String((err && err.message) || err).slice(0, 60), true);
    });
  }

  /* #1311: A SHORT WORD ON THE STRIP, AND IT STAYS LONG ENOUGH TO READ.
   *
   * This set the text and then cleared sayingSaid so the next tick
   * would repaint - which it did, 250ms later, over the top of the
   * message. So a tap that answered "the clip library is still
   * warming" showed nothing at all, and a button that was working
   * and refusing looked like a button that was dead. That is how the
   * operator came to report the video icon as unresponsive.
   *
   * The message now holds the strip for a few seconds; paintSaying
   * stands off until it expires. */
  var sayUntil = 0;

  function say(text) {
    var line = el('spSayingText');
    if (!line) return;
    sayUntil = Date.now() + 4000;
    sayingSaid = '__pine_never_said__'; /* never equal to a real print */
    sayingCrawl(line, text, 7);
  }

  /* ---------------------------------------------------------------- 4 */

  /* The tree opens the Pine Box panel. On the tablet that panel already
   * exists as the native drawer - broadcast, routing, the device list - so
   * the tree hands it over rather than building a second one that would
   * drift from it. Where there is no drawer, a small sheet stands in. */
  function buildTree() {
    var tree = make('button', 'sp-tree');
    tree.title = 'Pine Box - broadcast, levels and settings';
    tree.setAttribute('aria-label', 'Pine Box');
    tree.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<path d="M12 2 L17 9 H14 L18.5 15 H14.5 L20 21 H4 L9.5 15 H5.5 L10 9 H7 Z"/>'
      + '<rect x="11" y="21" width="2" height="2"/></svg>';
    tree.addEventListener('click', function () {
      if (root.PineViewChrome && root.PineViewChrome.openMenu() !== 'sheet') return;
      togglePanel();
    });
    return tree;
  }

  function togglePanel() {
    var box = el('spPanel');
    if (!box) return;
    box.hidden = !box.hidden;
  }

  function buildPanel() {
    var box = make('div', 'sp-panel');
    box.id = 'spPanel';
    box.hidden = true;
    box.appendChild(make('h4', '', 'Pine Box'));
    var rows = [
      ['Give this terminal the air', 'solo'],
      ['Let every page sound', 'clear'],
      ['Re-read the script', 'reload']
    ];
    for (var i = 0; i < rows.length; i += 1) {
      (function (label, action) {
        var b = make('button', 'sp-panel-row', label);
        b.addEventListener('click', function () { panelAction(action, b); });
        box.appendChild(b);
      })(rows[i][0], rows[i][1]);
    }
    box.appendChild(make('p', 'sp-panel-why',
      'The full desk - broadcast routing, levels and settings - is in the '
      + 'drawer: swipe in from the left edge.'));
    return box;
  }

  function panelAction(action, button) {
    var was = button.textContent;
    if (action === 'reload') { fetchedAt = 0; loadScreenplay(true); return; }
    button.textContent = 'working...';
    var body = action === 'solo'
      ? {listener: (typeof root.pineListenerId === 'function') ? root.pineListenerId() : ''}
      : {clear: true};
    api().post('/api/radio/solo', body).then(function () {
      button.textContent = was;
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 40);
    });
  }

  /* ---------------------------------------------------------------- 5 */

  var playerTrack = {};
  var playerVotes = null;

  function buildPlayer() {
    var box = make('div', 'sp-player');
    box.innerHTML =
      '<img id="spArt" class="sp-art" alt="">'
      + '<div class="sp-playmid">'
      + '<div class="sp-titleline"><div id="spTitle" class="sp-title"></div>'
      + '<div id="spVotes" class="sp-votes"></div></div>'
      + '<div id="spWho" class="sp-who"><span id="spArtist" class="sp-artist"></span>'
      + '<span id="spAlbum" class="sp-album"></span></div>'
      + '<canvas id="spSpectrum" class="sp-spectrum"></canvas>'
      + '<canvas id="spVoice" class="sp-voicemeter"></canvas>'
      /* [#1198] the readout that only exists while a level is moving */
      + '<div id="spLevelPill" class="sp-levelpill" aria-live="polite"></div>'
      + '<div class="sp-seekrow">'
      + '<i id="spAt" class="sp-time"></i>'
      + '<input id="spSeek" class="sp-seek" type="range" min="0" max="1000" value="0">'
      + '<i id="spLen" class="sp-time"></i>'
      + '</div></div>'
      + '<button id="spMixDot" class="sp-mixdot" type="button" '
      + 'title="Levels: voices, music, SFX, videos" aria-label="Levels"></button>'
      + '<div class="sp-transport">'
      + '<button id="spPrev" class="sp-tbtn" title="The station’s previous track" aria-label="The station’s previous track">⏮</button>'
      + '<button id="spNext" class="sp-tbtn" title="Skip to the next track" aria-label="Skip to the next track">⏭</button>'
      + '</div>';
    return box;
  }

  /* ---- #1198: THE METERS ARE THE LEVEL CONTROLS -------------------
   *
   * "I want to swipe my fingers on these spectra grams in order to set the
   *  volume. So if I swipe to the left it goes down and if I swipe to the
   *  right it goes up."
   *
   * The green bar is the music player, the amber one is the louder DJ voice,
   * and those are two of the four kinds on the level bus (audio-law.js,
   * #1192): 'music' and 'voice'. So the bar the operator is already looking
   * at to read a level becomes the thing that sets it.
   *
   * RELATIVE, NOT ABSOLUTE, and the reason is the page it lives on. An
   * absolute control means "the value is wherever your finger is", so the
   * first frame of any contact snaps the level to that x - and this card sits
   * in a column the operator scrolls with his thumb, an inch below a mixer
   * dot he taps. A finger that grazes the bar on the way past would slam the
   * music to 12% before the direction lock had anything to look at. Relative
   * costs nothing: the level starts where it was, moves by how far the finger
   * travelled, and a gesture that turns out not to be a level drag leaves the
   * level exactly as it found it. It also keeps the ceiling honest - these
   * two kinds reach 1.5, so an absolute map would put unity at two thirds of
   * the way along a bar with no marks on it.
   *
   * THE SCALE: one full width of the bar = the full range (0 to the kind's
   * ceiling). On the tablet's card that is about 340 px, so ~0.4% of level
   * per pixel - fine enough to land on a number, coarse enough to cross the
   * whole range in one swipe.
   *
   * INERTIA-FREE: the value is a pure function of the pointer's total dx from
   * where it went down. Nothing continues after release, nothing smooths.
   *
   * IT MUST NOT FIRE WHILE THE PAGE IS BEING SCROLLED, and the lock is cut in
   * two places on purpose:
   *   - `touch-action: pan-y` on both canvases (script-page.css) lets the
   *     compositor keep vertical panning. Once it claims the gesture we get a
   *     pointercancel and stand down; we never see the moves at all.
   *   - the script locks direction itself, because touch-action does nothing
   *     for a mouse: no move counts until the pointer has travelled 8 px, and
   *     at that moment |dx| <= |dy| means a scroll and this pointer is
   *     abandoned for good.
   *
   * IT MUST NOT FIGHT A TAP: under 8 px of travel nothing is armed, nothing
   * is captured, nothing is preventDefault'ed and no click is swallowed. A
   * tap on these bars still means whatever a tap on them meant.
   *
   * Arrow keys move it by 2% of the range, because a desk with a keyboard
   * should not need a mouse, and the canvases carry role="slider" with a live
   * aria-valuenow so a reader can say what the level is.
   */
  var LEVEL_DRAG_SLOP = 8;           /* px before a gesture has a direction */
  var LEVEL_NAMES = {music: 'MUSIC', voice: 'DJ VOICES'};
  var levelPillTimer = 0;

  function levelBus() {
    return (root.pineLevels && typeof root.pineLevels.apply === 'function')
      ? root.pineLevels : null;
  }

  function levelCeil(kind) {
    var bus = levelBus();
    var c = bus && bus.CEIL ? bus.CEIL[kind] : null;
    return typeof c === 'number' && c > 0 ? c : 1.5;
  }

  function levelNow(kind) {
    var bus = levelBus();
    if (!bus) return null;
    var m = null;
    try { m = bus.get() || {}; } catch (err) { return null; }
    return typeof m[kind] === 'number' ? m[kind] : 1;
  }

  function levelSay(kind, value) {
    return (LEVEL_NAMES[kind] || kind).toUpperCase() + ' '
      + Math.round(value * 100) + '%';
  }

  function levelPill(text, hold) {
    var pill = el('spLevelPill');
    if (!pill) return;
    pill.textContent = text;
    pill.classList.add('on');
    if (levelPillTimer) { clearTimeout(levelPillTimer); levelPillTimer = 0; }
    if (hold) return;
    levelPillTimer = setTimeout(function () {
      levelPillTimer = 0;
      var p = el('spLevelPill');
      if (p) p.classList.remove('on');
    }, 900);
  }

  /* The hairline that says WHERE on the bar the level currently sits - drawn
   * after PineMeters.draw, in the dpr transform it leaves behind. Without it
   * the control is invisible and the operator is dragging in the dark. */
  function levelMark(canvas, kind) {
    if (!canvas) return;
    var v = levelNow(kind);
    if (v === null) return;
    var w = canvas.clientWidth || 0;
    var h = canvas.clientHeight || 0;
    if (!w || !h) return;
    var g = canvas.getContext('2d');
    if (!g) return;
    var dpr = Math.min(2, root.devicePixelRatio || 1);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    var x = Math.max(0.5, Math.min(w - 0.5, (v / levelCeil(kind)) * w));
    g.globalAlpha = canvas.dataset.levelDragging ? 0.95 : 0.4;
    g.fillStyle = '#e8f0ff';
    g.fillRect(x - 0.5, 0, 1, h);
    g.globalAlpha = 1;
  }

  function levelDrag(canvas, kind) {
    if (!canvas || canvas.dataset.levelWired) return;
    canvas.dataset.levelWired = '1';
    canvas.setAttribute('role', 'slider');
    canvas.setAttribute('tabindex', '0');
    canvas.setAttribute('aria-label',
      (kind === 'music' ? 'Music level' : 'DJ voices level')
      + ' — swipe right to raise, left to lower');
    canvas.setAttribute('aria-valuemin', '0');
    canvas.setAttribute('aria-valuemax',
      String(Math.round(levelCeil(kind) * 100)));

    var aria = function () {
      var v = levelNow(kind);
      if (v === null) return;
      canvas.setAttribute('aria-valuenow', String(Math.round(v * 100)));
      canvas.setAttribute('aria-valuetext', Math.round(v * 100) + '%');
    };
    aria();

    var id = -1;
    var x0 = 0;
    var y0 = 0;
    var from = 1;
    var armed = false;
    var decided = false;

    var stand = function () {
      id = -1; armed = false; decided = false;
      if (canvas.dataset.levelDragging) delete canvas.dataset.levelDragging;
    };

    canvas.addEventListener('pointerdown', function (ev) {
      if (ev.button !== undefined && ev.button !== 0) return;
      var v = levelNow(kind);
      if (v === null) return;              /* no bus here: stay inert */
      id = ev.pointerId; x0 = ev.clientX; y0 = ev.clientY;
      from = v; armed = false; decided = false;
    });

    canvas.addEventListener('pointermove', function (ev) {
      if (ev.pointerId !== id) return;
      var dx = ev.clientX - x0;
      var dy = ev.clientY - y0;
      if (!decided) {
        if (Math.abs(dx) < LEVEL_DRAG_SLOP && Math.abs(dy) < LEVEL_DRAG_SLOP) return;
        decided = true;
        if (Math.abs(dx) <= Math.abs(dy)) { stand(); return; }   /* a scroll */
        armed = true;
        canvas.dataset.levelDragging = '1';
        try { canvas.setPointerCapture(ev.pointerId); } catch (err) { /* mouse */ }
      }
      if (!armed) return;
      if (ev.cancelable) ev.preventDefault();
      var bus = levelBus();
      if (!bus) return;
      var span = canvas.clientWidth || 1;
      var ceil = levelCeil(kind);
      var want = Math.max(0, Math.min(ceil, from + (dx / span) * ceil));
      bus.apply(kind, want);
      levelPill(levelSay(kind, want), true);
      aria();
    });

    var done = function (ev) {
      if (id !== -1 && ev.pointerId !== id) return;
      if (armed) {
        try { canvas.releasePointerCapture(ev.pointerId); } catch (err) { /* gone */ }
        var v = levelNow(kind);
        levelPill(levelSay(kind, v === null ? 0 : v), false);
      }
      stand();
      aria();
    };
    ['pointerup', 'pointercancel'].forEach(function (name) {
      canvas.addEventListener(name, done);
    });

    canvas.addEventListener('keydown', function (ev) {
      var step = ev.key === 'ArrowLeft' ? -0.02
        : ev.key === 'ArrowRight' ? 0.02 : 0;
      if (!step) return;
      var bus = levelBus();
      var v = levelNow(kind);
      if (!bus || v === null) return;
      ev.preventDefault();
      var ceil = levelCeil(kind);
      var want = Math.max(0, Math.min(ceil, v + step * ceil));
      bus.apply(kind, want);
      levelPill(levelSay(kind, want), false);
      aria();
    });

    /* The mixer popup and the drawer move the same numbers; the bar's
       hairline and its aria value follow them without a poll. */
    if (root.pineLevels && typeof root.pineLevels.onApply === 'function') {
      try { root.pineLevels.onApply(aria); } catch (err) { /* no watcher */ }
    }
  }

  /* THE PLAYHEAD IS A REAL SCRUB, and it moves THIS terminal's player.
   *
   * The station owns the broadcast clock; there is no route to move it, and
   * inventing one would desync every other listener. What this scrubs is the
   * element playing here - which is what a hand on a playhead means on the
   * device in front of you - and the labels say the position honestly. Back
   * and forward DO move the station's queue, because those routes exist
   * (/api/dj/prev, /api/dj/next) and skipping is a thing the whole house
   * hears by design. */
  function wirePlayer() {
    var seek = el('spSeek');
    var player = function () { return el('musicPlayer'); };
    var dragging = false;
    if (seek) {
      seek.addEventListener('pointerdown', function () { dragging = true; });
      var release = function () { dragging = false; };
      ['pointerup', 'pointercancel'].forEach(function (n) {
        seek.addEventListener(n, release);
      });
      seek.addEventListener('input', function () {
        var p = player();
        if (!p || !isFinite(p.duration) || !p.duration) return;
        p.currentTime = (Number(seek.value) / 1000) * p.duration;
      });
    }
    seek && (seek.dataset.dragging = '');
    /* [#1198] the two bars in this card are the two level controls */
    levelDrag(el('spSpectrum'), 'music');
    levelDrag(el('spVoice'), 'voice');
    var dot = el('spMixDot');                                    /* #1419 */
    if (dot) dot.addEventListener('click', function (ev) { ev.stopPropagation(); mixerOpen(); });
    var prev = el('spPrev');
    var next = el('spNext');
    if (prev) prev.addEventListener('click', function () { api().post('/api/dj/prev', {}); });
    if (next) next.addEventListener('click', function () { api().post('/api/dj/next', {}); });
    var art = el('spArt');
    if (art) {
      art.setAttribute('role', 'button');
      art.setAttribute('tabindex', '0');
      art.title = 'Open this album, its tracks, player, DJ files, analysis and queue controls';
      var album = function () {
        if (root.PineAlbum && typeof root.PineAlbum.open === 'function') {
          root.PineAlbum.open(playerTrack);
        }
      };
      art.addEventListener('click', album);
      art.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault(); album();
      });
    }
    var voteSeat = el('spVotes');
    if (voteSeat && root.PineVote && typeof root.PineVote.mount === 'function') {
      playerVotes = root.PineVote.mount(voteSeat, function () { return playerTrack; }, say);
    }

    /* The meters and the playhead ride requestAnimationFrame - numbers the
     * browser already has, no request of any kind. */
    var frame = 0;
    var tickN = 0;                    /* #1413c: the meters at the scope's pace */
    var specAt = 0;
    var specOk = false;
    var tick = function () {
      frame = requestAnimationFrame(tick);
      tickN = (tickN + 1) % SCOPE_EVERY;
      if (tickN) return;
      var spectrum = el('spSpectrum');
      /* #1413c: the layout read once a second - clientWidth forces a
         layout of a document the feed keeps dirty, every frame. */
      var nowMs = Date.now();
      if (nowMs - specAt > 1000) {
        specAt = nowMs;
        specOk = !!(spectrum && spectrum.isConnected && spectrum.clientWidth);
      }
      if (!spectrum || !specOk) return;
      var meters = root.PineMeters;
      if (meters) {
        meters.attach(['musicPlayer', 'djVoiceAudio0', 'djVoiceAudio1']);
        meters.draw(spectrum, meters.read('musicPlayer', 'music'), '#54d18b');
        meters.draw(el('spVoice'),
          meters.readLoudest(['djVoiceAudio0', 'djVoiceAudio1'], 'voice'), '#e3be63');
        levelMark(spectrum, 'music');                             /* [#1198] */
        levelMark(el('spVoice'), 'voice');                        /* [#1198] */
      }
      var p = player();
      if (p && isFinite(p.duration) && p.duration) {
        if (seek && !dragging) seek.value = String(Math.round((p.currentTime / p.duration) * 1000));
        var at = el('spAt'); var len = el('spLen');
        if (at) at.textContent = clock(p.currentTime);
        if (len) len.textContent = clock(p.duration);
      }
    };
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
    document.addEventListener('pointerdown', function () {
      if (root.PineMeters) root.PineMeters.wake();
    });
  }

  /* #1419: THE MIXER DOT.
   *
   * "Put a dot here that whenever I click it or tap it it brings up a
   *  pop-up that shows volume sliders for the voices, the music, the SFX,
   *  and the videos, and it allows me to adjust the volume levels of each
   *  of them individually and have it retain these settings and remember
   *  it next time."
   *
   * The levels are the same canonical listener values exposed in the native
   * drawer, Listen, and the global Levels sheet. */
  var MIXER_ROWS = [
    ['voice', 'Voices'], ['music', 'Music'], ['sfx', 'SFX'], ['video', 'Videos']
  ];
  function mixerRead() {
    var m = null;
    try { if (root.pineLevels && root.pineLevels.get) m = root.pineLevels.get(); } catch (err) { m = null; }
    if (!m) { try { m = JSON.parse(root.localStorage.getItem('pineListenerLevels') || '{}'); } catch (err) { m = {}; } }
    var out = {};
    MIXER_ROWS.forEach(function (row) {
      var v = Number(m && m[row[0]]);
      out[row[0]] = isFinite(v) ? Math.max(0, Math.min(2, v)) : 1;
    });
    return out;
  }
  function mixerWrite(values) {
    /* [#1192]: ONE ROAD, AND IT ANSWERS UNDER THE THUMB.
     *
     * window.pineLevels (audio-law.js) persists, moves everything this
     * document owns synchronously, coalesces the webview crossing and the
     * native video wall onto one animation frame, and knows which document
     * each element lives in.  Called straight off `input`, so the level is
     * true for what is sounding NOW and for every clip made after it.
     *
     * The old two lines stay as the fallback: in a host where the bus was
     * never loaded this file must still do what it used to. */
    try {
      if (root.pineLevels && typeof root.pineLevels.applyAll === 'function') {
        root.pineLevels.applyAll(values);
        return;
      }
    } catch (err) { /* the old road below */ }
    try { root.localStorage.setItem('pineMixer', JSON.stringify(values)); } catch (err) { /* private mode */ }
    try { if (root.pineMixer && root.pineMixer.set) root.pineMixer.set(values); } catch (err) { /* applied next time */ }
  }
  function mixerOpen() {
    var old = document.getElementById('spMixBack');
    if (old) { old.remove(); return; }
    var levels = mixerRead();
    var back = make('div', 'sp-mix-back');
    back.id = 'spMixBack';
    var box = make('div', 'sp-mix-box');
    var head = make('div', 'sp-mix-head');
    head.appendChild(make('b', '', 'Levels'));
    var reset = make('button', 'sp-mix-reset', 'Reset');
    reset.type = 'button';
    var shut = make('button', 'sp-mix-shut', '\u2715');
    shut.type = 'button';
    head.appendChild(reset);
    head.appendChild(shut);
    box.appendChild(head);
    var inputs = {};
    MIXER_ROWS.forEach(function (row) {
      var line = make('label', 'sp-mix-row');
      line.appendChild(make('span', 'sp-mix-name', row[1]));
      var range = document.createElement('input');
      range.type = 'range'; range.min = '0';
      range.max = '200';
      range.step = '1';
      range.value = String(Math.round(levels[row[0]] * 100));
      range.className = 'sp-mix-range';
      var val = make('span', 'sp-mix-val', range.value + '%');
      range.addEventListener('input', function () {
        val.textContent = range.value + '%';
        levels[row[0]] = Number(range.value) / 100;
        mixerWrite(levels);
      });
      inputs[row[0]] = {range: range, val: val};
      line.appendChild(range);
      line.appendChild(val);
      box.appendChild(line);
    });
    box.appendChild(make('div', 'sp-mix-note',
      'Remembered on this device. On top of the station\u2019s own levels, '
      + 'and they take effect as you drag \u2014 on what is playing now and '
      + 'on everything after it.'));                               /* [#1192] */
    reset.addEventListener('click', function () {
      MIXER_ROWS.forEach(function (row) {
        levels[row[0]] = 1;
        inputs[row[0]].range.value = '100';
        inputs[row[0]].val.textContent = '100%';
      });
      mixerWrite(levels);
    });
    shut.addEventListener('click', function () { back.remove(); });
    back.addEventListener('click', function (ev) { if (ev.target === back) back.remove(); });
    box.addEventListener('click', function (ev) { ev.stopPropagation(); });
    back.appendChild(box);
    document.body.appendChild(back);
  }
  /* Applied once at load too, so a remembered level is heard before the
     dot is ever touched. */
  try { if (root.pineMixer && root.pineMixer.apply) root.pineMixer.apply(); } catch (err) { /* later */ }

  function clock(v) {
    var t = Math.max(0, Math.round(Number(v) || 0));
    var m = Math.floor(t / 60);
    var s = t % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function paintPlayer(state) {
    var now = (state && state.now) || {};
    playerTrack = now;
    if (playerVotes && typeof playerVotes.paint === 'function') playerVotes.paint();
    var art = el('spArt');
    if (art) {
      var want = now.art || '';
      if (art.dataset.want !== want) {
        art.dataset.want = want;
        if (want) { art.src = want; art.hidden = false; }
        else { art.removeAttribute('src'); art.hidden = true; }
      }
      art.onerror = function () { art.hidden = true; };
    }
    var title = el('spTitle');
    if (title) title.textContent = now.title || 'the station';
    var artist = el('spArtist');
    var album = el('spAlbum');
    if (artist) artist.textContent = now.artist || 'Unknown artist';
    if (album) album.textContent = now.album || '';
  }

  /* ---------------------------------------------------------------- 6 */

  /* "Like an instant message correspondence" - newest at the bottom,
   * endless, auto-scrolling. APPEND ONLY: the whole reason this reads as a
   * conversation rather than a table is that rows never move once written.
   * Rebuilding the list each tick would also throw away the operator's
   * scroll position, which is the one thing an endless feed must not do. */
  var feedCrawlResize = null;
  var feedCrawlBox = null;
  var feedCrawlWidth = -1;

  function feedCrawlMeasure(viewport) {
    if (!viewport) return;
    var track = viewport.querySelector('.sp-msg-marquee-track');
    var first = track && track.firstElementChild;
    viewport.classList.toggle('is-moving',
      !!first && first.scrollWidth > viewport.clientWidth - 4);
  }

  function feedCrawlResizeNow() {
    if (!feedCrawlBox || feedCrawlBox.clientWidth === feedCrawlWidth) return;
    feedCrawlWidth = feedCrawlBox.clientWidth;
    feedCrawlBox.querySelectorAll('.sp-msg-marquee').forEach(feedCrawlMeasure);
  }

  function feedCrawlStart(box) {
    feedCrawlStop();
    feedCrawlBox = box;
    if (typeof root.ResizeObserver === 'function') {
      feedCrawlResize = new root.ResizeObserver(feedCrawlResizeNow);
      feedCrawlResize.observe(box);
    } else if (root.addEventListener) root.addEventListener('resize', feedCrawlResizeNow);
  }

  function feedCrawlStop() {
    if (feedCrawlResize) feedCrawlResize.disconnect();
    else if (root.removeEventListener) root.removeEventListener('resize', feedCrawlResizeNow);
    feedCrawlResize = null;
    feedCrawlBox = null;
    feedCrawlWidth = -1;
  }

  function feedSetActiveMarquee(box) {
    /* The feed can hold a long render history. Only the newest voicing
       receipt is still live, so it is the one that earns a moving marquee.
       Leaving every historical line on requestAnimationFrame made an idle
       tablet do the work of a row of news tickers. */
    var rows = box ? box.querySelectorAll('.sp-msg-ev[data-render-at]') : [];
    var newest = null;
    var newestAt = -1;
    for (var index = 0; index < rows.length; index += 1) {
      var candidate = rows[index];
      var at = Number(candidate.dataset.renderAt) || 0;
      if (at >= newestAt) { newest = candidate; newestAt = at; }
    }
    for (var item = 0; item < rows.length; item += 1) {
      var viewport = rows[item].querySelector('.sp-msg-marquee');
      if (viewport) viewport.classList.toggle('sp-msg-marquee-active', rows[item] === newest);
    }
  }

  function paintFeed(state) {
    var box = el('spFeed');
    if (!box) return;
    /* #1279: KEPT AND RE-SEATED, NOT APPENDED AND FROZEN.
     *
     * This drew each id once, in first-appearance order, and never
     * moved or refreshed it. That would be fine if rows arrived in the
     * order they sound - but a burst is published up to 58.8 SECONDS
     * before any of it is audible (measured; mean 5.7 future-stamped
     * rows per poll). Replayed against a real 16-poll sequence this
     * function's order came out 104 of 253 pairs discordant - 41.1% -
     * with interjections that sound 13-40s EARLIER parked underneath
     * lines nobody had said yet, for the life of the pane.
     *
     * Rows are held by id now and put back in `air_at` order on every
     * paint. That key is itself a moving target, but re-seating lets
     * the feed CORRECT ITSELF when a stamp moves instead of being
     * frozen wrong. Their words and state are refreshed too: a row
     * drawn while `prepared` used to still read `prepared` long after
     * it had aired. */
    var rows = (state && state.chat) || [];
    if (rows.length > FEED_MAX) {
      rows = rows.slice().sort(function (a, b) {
        return Number((a && (a.air_at || a.ts)) || 0)
          - Number((b && (b.air_at || b.ts)) || 0);
      }).slice(-FEED_MAX);
    }
    var added = 0;
    var want = [];
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var id = String((row && row.id) || '');
      if (!id) continue;
      var node = feedNodes[id];
      if (!node) {
        node = feedRow(row);
        feedNodes[id] = node;
        seen[id] = true;
        added += 1;
      } else {
        feedDress(node, row);
      }
      node.pineAt = Number(row.air_at || row.ts || 0);
      want.push(node);
    }
    if (want.length) {
      want.sort(function (a, b) { return a.pineAt - b.pineAt; });
      /* #1287: an insertBefore on an attached node is a detach and an
         attach, so stitching an already-correct list still takes every
         row out of the document for an instant. Check first: with the
         treadmill above gone, the order matches on nearly every paint
         and this loop does nothing at all. */
      var settled = true;
      var walk = box.firstChild;
      for (var c2 = 0; c2 < want.length; c2 += 1) {
        while (walk && /sp-msg-ev/.test(walk.className)) walk = walk.nextSibling;
        if (walk !== want[c2]) { settled = false; break; }
        walk = walk.nextSibling;
      }
      if (!settled) {
        var cursor = box.firstChild;
        for (var w = 0; w < want.length; w += 1) {
          /* #1428d: STEP OVER THE EVENT ROWS, exactly as the settled
             test above does. They are appended as they happen and take
             no part in air-time order; walking onto one made
             `want[w] === cursor` false for a row already in its right
             place, and insertBefore on an attached node is a detach and
             an attach. Measured: 240 such moves in eight seconds on a
             feed whose order was already perfect. */
          while (cursor && /sp-msg-ev/.test(String(cursor.className || ''))) {
            cursor = cursor.nextSibling;
          }
          if (want[w] === cursor) { cursor = cursor.nextSibling; continue; }
          box.insertBefore(want[w], cursor);
        }
      }
    }
    /* The station also does things that are not speech. */
    var log = (state && state.activity_log) || [];
    for (var k = 0; k < log.length; k += 1) {
      var ev = log[k];
      /* Several receipts can land during the same second. Include the
         durable line id so an SFX clip and its reaction cannot hide each
         other behind the old timestamp-and-stage key. */
      var key = 'ev' + (ev && ev.at) + String((ev && ev.stage) || '')
        + String((ev && ev.line) || '') + String((ev && ev.text) || '');
      if (!ev || seen[key]) continue;
      seen[key] = true;
      /* A voicing event names a line but historically carries no cast
         identity. Join it to the chat row before painting so the portrait,
         recipient and operation context describe the person whose line is
         actually being rendered. The event's own stage/detail/text win. */
      var subject = null;
      if (ev.line) {
        for (var m = rows.length - 1; m >= 0; m -= 1) {
          if (String((rows[m] || {}).id || '') === String(ev.line)) {
            subject = rows[m]; break;
          }
        }
      }
      box.appendChild(eventRow(Object.assign({}, subject || {}, ev)));
      added += 1;
    }
    /* Activity has its own stream and therefore never belongs in the chat
       window above. Bound it separately, oldest first, so a busy booth still
       keeps its most recent SFX, render, and orchestration receipts visible. */
    var events = [].slice.call(box.children).filter(function (child) {
      return /sp-msg-ev/.test(String(child.className || ''));
    });
    for (var eventAt = 0; eventAt < events.length - FEED_EVENT_MAX; eventAt += 1) {
      events[eventAt].remove();
    }
    /* #1287: THE TRIM STOPS EVICTING ROWS IT STILL WANTS.
     *
     * #1279 trimmed on `box.children.length > FEED_MAX`, and the pane
     * holds activity rows and orphans as well as chat rows - so
     * several WANTED rows never fit inside the 240. The trim evicted
     * them from the front, forgot them, and the next paint recreated
     * them, re-inserted them at the front, and the trim evicted six
     * again. Measured: 65,023 detach/re-attach events in 9.2 minutes,
     * 7,055 a minute, at 3.67 paints a second - the largest single
     * reason a row moves under the operator's finger, and my own.
     *
     * Orphans go first, the cap counts only what is wanted, and a row
     * still in `want` is never evicted. */
    var keep = Object.create(null);
    for (var w2 = 0; w2 < want.length; w2 += 1) {
      var wid = want[w2].getAttribute('data-line');
      if (wid) keep[wid] = 1;
    }
    var kids = [].slice.call(box.children);
    for (var k2 = 0; k2 < kids.length; k2 += 1) {
      var kid = kids[k2];
      var kidId = kid.getAttribute && kid.getAttribute('data-line');
      if (!kidId || keep[kidId]) continue;
      if (/sp-msg-ev/.test(kid.className)) continue;   /* an event row */
      box.removeChild(kid);                            /* an orphan */
      delete feedNodes[kidId];
      if (feedLive === kidId) feedLive = '';
    }
    var over = want.length - FEED_MAX;
    for (var t2 = 0; t2 < over; t2 += 1) {
      var old = want[t2];
      var oldId = old && old.getAttribute && old.getAttribute('data-line');
      if (old && old.parentNode === box) box.removeChild(old);
      if (oldId) {
        delete feedNodes[oldId];
        if (feedLive === oldId) feedLive = '';
      }
    }
    feedSetActiveMarquee(box);
    if (!added && over <= 0) return;
    if (feedStick) box.scrollTop = box.scrollHeight;
  }

  var FEED_OPERATIONS = {
    ad: "Sponsor's Copy", analysis: 'Analysis', banter: 'Studio Banter',
    caller: 'Phone Line', caller2: 'Second Phone Line', cover: 'Cover Story',
    gallery: 'Gallery Wall', gold: 'Gold Segment', image_analysis: 'Image Analysis',
    interject: 'Studio Interjection', manager: 'Memo From Upstairs',
    marker: 'Broadcast Marker', music: 'Turntable', news: 'News Desk',
    reply: 'Studio Reply', sfx: 'SFX Cue', sfxguy: 'SFX Desk',
    station_id: 'Station Ident', sting: 'SFX Cue', track_talk: 'Turntable',
    voicing: 'Voice Rendering', writing: 'Script Writing', action: 'Station Operation'
  };

  function feedHuman(value) {
    var key = String(value || '').trim().toLowerCase();
    if (FEED_OPERATIONS[key]) return FEED_OPERATIONS[key];
    if (!key) return 'Broadcast Operation';
    return key.replace(/[_-]+/g, ' ').replace(/(^|\s)([a-z])/g,
      function (_, gap, letter) { return gap + letter.toUpperCase(); });
  }

  function feedWords(row) {
    return String((row && (row.text || row.detail || row.analysis)) || '')
      .replace(/\s+/g, ' ').trim();
  }

  function feedSpeaker(row) {
    return String((row && (row.name || row.speaker || row.who)) || '').trim();
  }

  function feedOperation(row) {
    row = row || {};
    var stage = String(row.stage || '').toLowerCase();
    var kind = String(row.kind || '').toLowerCase();
    var round = String(row.round || '').toLowerCase();
    /* A renderer is not a speaker. The generic worker label made a useful
       progress row read like infrastructure noise; name the person whose
       words are in flight instead. */
    if (stage === 'voicing') {
      var speaker = feedSpeaker(row);
      return speaker ? speaker + ' rendering' : 'Voice rendering';
    }
    if (stage === 'sfx') return 'The SFX Guy played a clip';
    if (stage === 'sfxguy') return 'The SFX Guy';
    if (stage === 'sfxreaction') {
      return (feedSpeaker(row) || 'A host') + ' reacts to SFX';
    }
    if (stage) return feedHuman(stage);
    if (kind === 'interject' || kind === 'image_analysis' || kind === 'sfx') {
      return feedHuman(kind);
    }
    return feedHuman(round || kind || 'dialogue');
  }

  function feedOrchestrated(row) {
    row = row || {};
    if (row.orchestrator === true || row.orchestrated === true) return true;
    var trace = row.trace || {};
    if (trace.written && Object.keys(trace.written).length) return true;
    var proof = [row.producer, row.actor, row.by, row.source, row.detail]
      .map(function (value) { return String(value || '').toLowerCase(); }).join(' ');
    return /\borchestrator\b/.test(proof);
  }

  function feedPurpose(row) {
    row = row || {};
    var explicit = row.purpose || row.for || ((row.trace || {}).written || {}).for;
    if (explicit) return String(explicit).replace(/\s+/g, ' ').trim();
    var speaker = feedSpeaker(row);
    var stage = String(row.stage || '').toLowerCase();
    if (stage === 'voicing') {
      var total = Math.max(0, Number(row.script_total) || 0);
      var index = Math.max(0, Math.min(total, Number(row.script_index) || 0));
      if (total) {
        return 'line ' + index + ' of ' + total + ' - '
          + Math.round((1 / total) * 100) + '% of script; '
          + Math.round((index / total) * 100) + '% queued through render';
      }
      return speaker ? 'rendering a line for ' + speaker : 'rendering the next broadcast line';
    }
    if (stage === 'writing') return 'preparing dialogue for a scheduled segment';
    if (stage === 'action') return 'coordinating the broadcast and its prepared material';
    if (stage === 'sfx') return 'confirmed by audible playout; written to the SFX rotation';
    if (stage === 'sfxguy') return 'confirmed by audible playout; the prepared interjection landed';
    if (stage === 'sfxreaction') return 'the one-in-three host reaction landed after the clip';
    if (String(row.kind || '').toLowerCase() === 'sfx') {
      return speaker ? 'punctuating ' + speaker + "'s segment" : 'punctuating the live segment';
    }
    return speaker ? 'line for ' + speaker : 'broadcast activity';
  }

  function feedAvatar(row) {
    var speaker = feedSpeaker(row) || (feedOrchestrated(row) ? 'Orchestrator' : 'Booth');
    var avatar = itinAvatar({who: speaker, seat: row && row.who,
      kind: row && (row.kind || row.stage)});
    avatar.classList.add('sp-msg-avatar');
    avatar.title = speaker;
    avatar.dataset.speaker = speaker;
    return avatar;
  }

  function feedCrawl(words) {
    var viewport = make('span', 'sp-msg-text sp-msg-marquee');
    viewport.appendChild(make('span', 'sp-msg-marquee-track'));
    feedCrawlDress(viewport, words);
    return viewport;
  }

  function feedCrawlDress(viewport, words) {
    if (!viewport) return;
    var body = String(words || '').replace(/\s+/g, ' ').trim() || 'No details were recorded.';
    if (viewport.dataset.words === body) return;
    var track = viewport.querySelector('.sp-msg-marquee-track');
    if (!track) {
      track = make('span', 'sp-msg-marquee-track');
      viewport.replaceChildren(track);
    }
    viewport.dataset.words = body;
    track.replaceChildren();
    var first = make('span', '', body);
    first.setAttribute('data-dialogue-text', 'true');
    track.appendChild(first);
    var again = make('span', '', body);
    again.setAttribute('aria-hidden', 'true');
    track.appendChild(again);
    viewport.setAttribute('aria-label', body);
    track.style.setProperty('--sp-feed-crawl',
      Math.max(12, Math.min(58, body.length / 7.5)) + 's');
    /* A short line stays put. Measure after placement as well, since a
       sentence that fits on the desktop may need to move on the tablet. */
    viewport.classList.toggle('is-moving', body.length > 34);
    root.requestAnimationFrame(function () {
      if (!viewport.isConnected) return;
      feedCrawlMeasure(viewport);
    });
  }

  function feedRenderProgress(row) {
    var total = Math.max(0, Number(row && row.script_total) || 0);
    var index = Math.max(0, Math.min(total, Number(row && row.script_index) || 0));
    if (String((row && row.stage) || '').toLowerCase() !== 'voicing' || !total) return null;
    return {index: index, total: total, contribution: 100 / total,
      complete: (index / total) * 100};
  }

  function feedFrame(row, extraClass) {
    var line = make('div', 'sp-msg' + (extraClass ? ' ' + extraClass : ''));
    line.setAttribute('role', 'button');
    line.setAttribute('tabindex', '0');
    line.appendChild(feedAvatar(row));
    var context = make('span', 'sp-msg-context');
    var operation = make('b', 'sp-msg-who sp-msg-operation', feedOperation(row));
    context.appendChild(operation);
    var purpose = make('span', 'sp-msg-purpose');
    var purposeText = make('span', 'sp-msg-purpose-text', feedPurpose(row));
    purpose.appendChild(purposeText);
    context.appendChild(purpose);
    line.appendChild(context);
    var body = feedCrawl(feedWords(row));
    line.appendChild(body);
    var progress = make('span', 'sp-msg-render-progress');
    progress.hidden = true;
    var progressFill = make('span', 'sp-msg-render-progress-fill');
    progress.appendChild(progressFill);
    line.appendChild(progress);
    line.pineFeedNodes = {operation: operation, purpose: purpose,
      purposeText: purposeText, body: body, progress: progress,
      progressFill: progressFill, badge: null};
    return line;
  }

  function feedRow(row) {
    /* #1279: NOT from `row.aired === "airing"`. That is spelled right
       and is unreachable - `airing` is attached only to speaking_now /
       stream_now, never to a chat row (measured: 0 of 317 across 16
       polls), so this pane has never once marked the line being said.
       markFeedLive() does it from the live pointer, every tick. */
    var line = feedFrame(row);
    line.dataset.line = String(row.id || '');
    line.pineRow = row;
    feedDress(line, row);
    line.addEventListener('click', function () { feedDetailOpen(line.pineRow || row); });
    line.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      ev.preventDefault(); feedDetailOpen(line.pineRow || row);
    });
    return line;
  }

  /* #1279: a row's words and state as they are NOW. A row used to be
     drawn once and never touched again, so one drawn while it was
     `prepared` still read `prepared` long after it had aired. */
  function feedDress(line, row) {
    line.pineRow = row;
    var parts = line.pineFeedNodes;
    var head = parts ? parts.operation : line.querySelector('.sp-msg-operation');
    var purpose = parts ? parts.purpose : line.querySelector('.sp-msg-purpose');
    var purposeText = parts ? parts.purposeText : line.querySelector('.sp-msg-purpose-text');
    var body = parts ? parts.body : line.querySelector('.sp-msg-marquee');
    var progress = parts ? parts.progress : line.querySelector('.sp-msg-render-progress');
    var progressFill = parts ? parts.progressFill : line.querySelector('.sp-msg-render-progress-fill');
    var operation = feedOperation(row);
    var why = feedPurpose(row);
    if (head && head.textContent !== operation) head.textContent = operation;
    if (purposeText && purposeText.textContent !== why) purposeText.textContent = why;
    var orchestrated = feedOrchestrated(row);
    var badge = parts ? parts.badge : purpose && purpose.querySelector('.sp-msg-orchestrator');
    if (orchestrated && !badge) {
      badge = make('em', 'sp-msg-orchestrator', 'Orchestrator');
      badge.title = 'Prepared or carried out by the orchestrator';
      purpose.appendChild(badge);
      if (parts) parts.badge = badge;
    } else if (!orchestrated && badge) {
      badge.remove();
      if (parts) parts.badge = null;
    }
    feedCrawlDress(body, feedWords(row));
    var render = feedRenderProgress(row);
    line.classList.toggle('sp-msg-render', !!render);
    if (progress) progress.hidden = !render;
    if (render && progressFill) {
      progressFill.style.width = render.complete.toFixed(1) + '%';
      progress.title = 'Line ' + render.index + ' of ' + render.total
        + ': this line contributes ' + render.contribution.toFixed(1)
        + '%; render queue is ' + render.complete.toFixed(1) + '% complete.';
      progress.setAttribute('aria-label', progress.title);
    }
    /* [#1200] a clip deleted from the library reads as gone in the feed. */
    if (line.pineDeleted !== !!row.deleted) {
      line.pineDeleted = !!row.deleted;
      line.classList.toggle('sp-deleted', !!row.deleted);
    }
    var state = String(row.aired || '');
    if (line.pineState !== state) {
      line.pineState = state;
      line.classList.toggle('pending', state === 'prepared');
    }
  }

  /* #1279: THE LINE THAT IS SOUNDING, marked from the live pointer and
     re-asserted on every tick, so it cannot be stranded by a row that
     was drawn before it started. */
  function markFeedLive(id) {
    var want = String(id || '');
    if (want === feedLive) return;
    var was = feedLive && feedNodes[feedLive];
    if (was) was.classList.remove('airing');
    feedLive = want;
    var node = want && feedNodes[want];
    if (node) node.classList.add('airing');
  }

  function eventRow(ev) {
    var line = feedFrame(ev, 'sp-msg-ev');
    line.pineEvent = ev;
    if (ev.line) line.dataset.line = String(ev.line);
    var stage = String(ev.stage || 'station');
    if (stage.toLowerCase() === 'voicing') {
      line.dataset.renderAt = String(Number(ev.at) || 0);
    }
    /* Activity events carry the live render receipt. Dress them just like
       script rows so speaker identity, line contribution, and progress are
       visible instead of reverting to a generic infrastructure event. */
    feedDress(line, ev);
    line.title = 'Open details for this ' + stage + ' event';
    line.addEventListener('click', function () { feedDetailOpen(line.pineEvent || ev); });
    line.addEventListener('keydown', function (key) {
      if (key.key !== 'Enter' && key.key !== ' ') return;
      key.preventDefault(); feedDetailOpen(line.pineEvent || ev);
    });
    return line;
  }

  function feedDetailActions(detail, row, stage, words) {
    var actions = make('div', 'sp-feed-detail-actions');
    var lineId = String(row.line || row.id || '');
    if (lineId) {
      var jump = make('button', '', 'Jump to this line');
      jump.type = 'button';
      jump.addEventListener('click', function () {
        detail.close(); resumeAirFollow('feed detail'); jumpToLine(lineId);
      });
      actions.appendChild(jump);
    }
    var trace = make('button', '', 'Inspect the pipeline');
    trace.type = 'button';
    trace.addEventListener('click', function () {
      if (root.PineConsoleTrace && root.PineConsoleTrace.open) {
        root.PineConsoleTrace.open({stage: stage, detail: String(row.detail || words),
          text: String(row.text || ''), line: lineId, at: Number(row.at || row.air_at) || 0,
          _flow: row._flow || null});
      }
    });
    actions.appendChild(trace);
    detail.box.appendChild(actions);
  }

  function feedAnalysisHeading(text) {
    return make('h3', 'sp-analysis-heading', text);
  }

  function feedAnalysisRender(mount, detail, row, data) {
    while (mount.firstChild) mount.removeChild(mount.firstChild);
    var dossier = make('article', 'sp-analysis-dossier');
    var status = make('div', 'sp-analysis-status', String(data.status ||
      'The station did not return a generation status for this analysis.'));
    dossier.appendChild(status);

    var top = make('div', 'sp-analysis-top');
    var picture = (data && data.image) || {};
    var figure = make('figure', 'sp-analysis-figure');
    if (picture.url) {
      var image = document.createElement('img');
      image.alt = 'Image analyzed by the station: ' + String(picture.name || 'gallery image');
      image.loading = 'eager';
      image.src = stationUrl(picture.url);
      image.addEventListener('error', function () {
        image.hidden = true;
        figure.classList.add('is-missing');
      });
      figure.appendChild(image);
    } else figure.classList.add('is-missing');
    var caption = make('figcaption', '', String(picture.name || row.image || 'Analyzed image'));
    figure.appendChild(caption);
    top.appendChild(figure);

    var reading = make('section', 'sp-analysis-reading');
    reading.appendChild(feedAnalysisHeading('What the vision model interpreted'));
    reading.appendChild(make('p', 'sp-analysis-copy', String(data.analysis || row.analysis ||
      'No interpretation was retained for this image.')));
    var model = [];
    if (data.model) model.push(String(data.model));
    if (Number(data.ms)) model.push((Number(data.ms) / 1000).toFixed(1) + ' seconds');
    if (model.length) reading.appendChild(make('div', 'sp-analysis-meta', model.join(' / ')));
    top.appendChild(reading);
    dossier.appendChild(top);

    dossier.appendChild(feedAnalysisHeading('Dialogue generated from this analysis'));
    var sections = Array.isArray(data.sections) ? data.sections : [];
    if (!sections.length) {
      dossier.appendChild(make('p', 'sp-analysis-empty',
        'No linked script is banked yet. This view will show it here as soon as the writing room stores it.'));
    }
    sections.forEach(function (section) {
      var group = make('section', 'sp-analysis-dialogue');
      var head = make('div', 'sp-analysis-dialogue-head');
      head.appendChild(make('b', '', String(section.title || 'Gallery dialogue')));
      var state = String(section.state || 'prepared');
      head.appendChild(make('span', 'sp-analysis-state ' + state, state));
      group.appendChild(head);
      var provenance = String(section.connection || 'linked image analysis');
      if (section.inferred) provenance += ' / recovered from an older image-bound segment';
      group.appendChild(make('p', 'sp-analysis-connection',
        provenance + ' / ' + Number((section.lines || []).length) + ' line(s)'));
      (section.lines || []).forEach(function (line) {
        var canJump = line.id && !/^prepared:/.test(String(line.id));
        var turn = make(canJump ? 'button' : 'div', 'sp-analysis-turn');
        if (canJump) {
          turn.type = 'button';
          turn.title = 'Jump to this dialogue in the script';
          turn.addEventListener('click', function () {
            detail.close(); resumeAirFollow('image analysis dialogue'); jumpToLine(String(line.id));
          });
        }
        turn.appendChild(itinAvatar({who: line.name || line.who, seat: line.who}));
        var body = make('span', 'sp-analysis-turn-body');
        body.appendChild(make('b', '', String(line.name || line.who || 'Speaker')));
        body.appendChild(make('span', '', String(line.text || '')));
        turn.appendChild(body);
        if (line.recorded) {
          var ready = make('em', 'sp-analysis-ready', 'recorded');
          ready.title = 'Finished voice media is already in the cupboard';
          turn.appendChild(ready);
        }
        group.appendChild(turn);
      });
      dossier.appendChild(group);
    });

    dossier.appendChild(feedAnalysisHeading('Generation trail'));
    var trail = make('ol', 'sp-analysis-trail');
    (data.trail || []).forEach(function (step) {
      var item = make('li', 'sp-analysis-step ' + String(step.state || 'waiting'));
      item.appendChild(make('b', '', String(step.label || 'Pipeline step')));
      item.appendChild(make('span', '', String(step.detail || '')));
      trail.appendChild(item);
    });
    dossier.appendChild(trail);

    var made = picture.made || {};
    var source = make('details', 'sp-analysis-source');
    source.appendChild(make('summary', '', 'Prompts, source image, and model details'));
    var table = make('table', 'sp-feed-detail-table sp-analysis-table');
    itinFact(table, 'Image generation request', made.request);
    itinFact(table, 'Image model', made.model);
    itinFact(table, 'Image render time', made.seconds ? String(made.seconds) + ' seconds' : '');
    itinFact(table, 'Vision prompt', data.prompt);
    itinFact(table, 'Vision model', data.model);
    itinFact(table, 'Analysis id', data.id || row.id);
    itinFact(table, 'Analyzed at', data.at ? sceneClock({at: data.at}) : '');
    itinFact(table, 'Recovered from ledger', data.from_ledger ? 'yes' : 'no');
    source.appendChild(table);
    dossier.appendChild(source);
    mount.appendChild(dossier);
    feedDetailActions(detail, row, 'image_analysis', String(row.text || ''));
  }

  function feedAnalysisOpen(detail, row) {
    var mount = make('div', 'sp-analysis-mount');
    mount.appendChild(make('div', 'sp-analysis-loading', 'Following the image through the writing room...'));
    detail.box.appendChild(mount);
    var lineId = String(row.line || row.id || '');
    if (!lineId || !api() || !api().get) {
      feedAnalysisRender(mount, detail, row, {
        id: lineId, image: {}, analysis: row.analysis || '', sections: [], trail: [],
        status: 'This analysis has no retained identity, so its generated script cannot be followed.'
      });
      return;
    }
    var path = '/api/dj/image-analysis/' + encodeURIComponent(lineId)
      + '?text=' + encodeURIComponent(String(row.text || ''))
      + '&at=' + encodeURIComponent(String(Number(row.air_at || row.at || row.ts) || 0));
    api().get(path).then(function (data) {
      if (!detail.back.isConnected) return;
      feedAnalysisRender(mount, detail, row, data || {});
    }).catch(function (err) {
      if (!detail.back.isConnected) return;
      feedAnalysisRender(mount, detail, row, {
        id: lineId, image: {}, analysis: row.analysis || '', sections: [], trail: [],
        status: 'The generation trail could not be loaded: ' + String((err && err.message) || err || 'unknown error')
      });
    });
  }

  function feedDetailOpen(row) {
    row = row || {};
    var isEvent = !row.id && (row.stage || row.detail);
    var stage = String(row.stage || row.kind || (isEvent ? 'station' : 'dialogue'));
    var words = String(row.text || row.detail || '').trim();
    var title = stage === 'image_analysis'
      ? 'Image analysis: ' + String(row.image || words.replace(/^Image analysis complete:\s*/i, '') || 'gallery image')
      : stage === 'voicing' && words
      ? 'Voicing: ' + words.split(/\s+/).slice(0, 9).join(' ')
      : (isEvent ? stage : String(row.name || row.who || 'Dialogue'));
    var detail = sheetShell('spFeedDetail', 'sp-feed-detail', title);
    if (root.PineDuck && root.PineDuck.hold) {
      root.PineDuck.hold('sp-spFeedDetail', root.PineDuck.REPORT, detail.back);
    }
    var graph = flowIconButton('sp-feed-detail-graph', 'c:chart--network',
      'Open this line in its scheduled node graph');
    graph.disabled = !(row.line || row.id);
    graph.addEventListener('click', function () {
      graph.disabled = true;
      itineraryFlowForLine({id: String(row.line || row.id || ''), text: String(row.text || words),
        said: String(row.text || words), at: Number(row.air_at || row.at) || 0,
        kind: String(row.kind || row.round || '')}, detail.close)
        ['catch'](function (err) {
          graph.disabled = false;
          detail.say(String((err && err.message) || err), true);
        });
    });
    detail.head.insertBefore(graph, detail.x);
    if (stage === 'image_analysis') {
      feedAnalysisOpen(detail, row);
      return detail;
    }
    if (words) detail.box.appendChild(make('p', 'sp-feed-detail-line', words));
    var table = make('table', 'sp-feed-detail-table');
    itinFact(table, 'Operation', feedOperation(row));
    itinFact(table, 'Purpose', feedPurpose(row));
    itinFact(table, 'Performed by', feedOrchestrated(row) ? 'Orchestrator' : 'Station');
    itinFact(table, 'Activity', stage);
    itinFact(table, 'What is happening', row.detail);
    itinFact(table, 'Dialogue', row.text);
    itinFact(table, 'Speaker', row.name || row.who);
    itinFact(table, 'Voice', row.voice);
    itinFact(table, 'Engine', row.engine);
    itinFact(table, 'State', row.aired || row.status);
    itinFact(table, 'Line id', row.line || row.id);
    itinFact(table, 'Scheduled for air', row.air_at || row.at);
    itinFact(table, 'Media', row.media || row.clip_media || row.url);
    detail.box.appendChild(table);
    feedDetailActions(detail, row, stage, words);
    return detail;
  }

  /* ---------------------------------------------------------------- 7 */

  function loadScreenplay(force) {
    var now = Date.now();
    if (fetching) return;
    if (!force && now - fetchedAt < SCREENPLAY_REST_MS) return;
    /* #1273b: a FORCED read is one the page asked for because the line
       it needs is missing (#1271). Asking for the cached copy would
       hand back the very page that just failed to contain it - measured
       16.1s old, against 2.1s with `fresh`. The rest poll stays cached,
       and so does the hour before: it is closed, 238 kB, and the server
       holds it for fifteen minutes. */
    var live = force ? '?fresh=1' : '';
    fetching = true;
    api().get('/api/screenplay').then(function (index) {
      var hours = (index && index.hours) || [];
      if (!hours.length) throw new Error('no hours written yet');
      hourKey = String(hours[0].key || '');
      /* #1268: THE READING DOES NOT END BECAUSE THE HOUR DID.
       *
       * "I want to put on my reading glasses and watch the pine box go
       *  through an endless reading that is endlessly streamed."
       *
       * This asked for hours[0] and nothing else, so at the top of
       * every hour the whole script was replaced by a nearly empty
       * page - measured at the 3 PM turn, 350 entries down to 0 - and
       * the reader's place went with it. Worse, a burst that straddles
       * the turn is still SOUNDING while the lines it is saying have
       * just left the page, so the highlight has nothing to land on.
       *
       * The hour before is carried too, above it and in order. The
       * window stays bounded: as the clock rolls, hours[1] becomes the
       * hour that just ended and the one before it drops off the top,
       * so this is always one to two hours of script and never grows.
       */
      var before = hours[1] && Number(hours[1].lines || 0) > 0
        ? String(hours[1].key || '') : '';
      /* #1276: THE HOUR THAT IS OVER IS FETCHED ONCE.
       *
       * This asked for both hours on every poll AND every chase. The
       * earlier hour is 238 kB, it is closed, and the server holds it
       * for fifteen minutes - the answer cannot change. Worse,
       * `fetching` is one latch across the whole Promise.all, so while
       * that 238 kB was in flight the #1271 chase returned at
       * `if (fetching) return;` and the live line could not be
       * collected. Measured on the tablet: thirty seconds after opening
       * the view, script rendered, nothing lit, because the sounding
       * line was not on the page yet.
       *
       * It is kept until the clock rolls and a different hour becomes
       * the one before. */
      var want = [api().get('/api/screenplay/'
        + encodeURIComponent(hourKey) + live)];
      if (before && before === beforeKey && beforePage) {
        want.push(Promise.resolve(beforePage));        /* already held */
      } else if (before) {
        want.push(api().get('/api/screenplay/' + encodeURIComponent(before))
          .then(function (page) {
            beforeKey = before; beforePage = page; return page;
          }, function () { return null; }));   /* its loss is survivable */
      } else {
        beforeKey = ''; beforePage = null;
      }
      return Promise.all(want).then(function (got) {
        return {now: got[0] || {}, was: got[1] || null,
          nowKey: hourKey, wasKey: before};
      });
    }).then(function (both) {
      var page = both.now;
      /* Each element remembers WHICH HOUR it belongs to, so a note put
         on a line from the earlier hour is filed against that hour and
         not against the one on screen. */
      function stamp(list, key) {
        var out = [];
        for (var i = 0; i < (list || []).length; i += 1) {
          var it = list[i];
          if (it && typeof it === 'object') { it.hour = key; out.push(it); }
        }
        return out;
      }
      elements = screenplayOrder(stamp(both.was && both.was.elements, both.wasKey),
        stamp(page.elements, both.nowKey));
      scriptAsOf = Number(page.at) || (Date.now() / 1000);
      fetchedAt = Date.now();
      fetching = false;
      paintScript(page, both.was);
    }, function (err) {
      fetching = false;
      var box = el('spScript');
      if (box && !box.children.length) {
        box.appendChild(make('p', 'sp-empty',
          'The script could not be read: ' + ((err && err.message) || err)));
      }
    });
  }

  var scriptAsOf = 0;
  var scriptOrder = [];
  var sceneNodes = new Map();
  var segmentCounts = Object.create(null);

  var SCENE_NAMES = {
    ad: "Sponsor's Copy", aside: 'Studio Aside', banter: 'Studio Banter',
    caller: 'Phone Line', caller2: 'Second Phone Line', cover: 'Cover Story',
    gallery: 'Gallery Wall', gold: 'Gold Segment', manager: 'Memo From Upstairs',
    news: 'News Desk', reply: 'Studio Reply', sfxguy: 'SFX Desk',
    station_id: 'Station Ident', track_talk: 'Turntable'
  };

  function sceneClock(item) {
    var raw = String((item && item.text) || '');
    var written = raw.match(/(?:^|\s-\s)(\d{1,2}:\d{2}\s*(?:AM|PM))\s*$/i);
    if (written) return written[1].replace(/\s+/g, ' ').toUpperCase();
    var stamp = Number(item && (item.at || item.air_at));
    if (!isFinite(stamp) || stamp <= 0) return '--:--';
    try {
      return new Date(stamp * 1000).toLocaleTimeString([], {
        hour: 'numeric', minute: '2-digit'
      });
    } catch (err) { return '--:--'; }
  }

  function sceneName(item) {
    var raw = String((item && item.text) || '').trim();
    var bits = raw.split(/\s+-\s+/);
    var named = '';
    if (bits.length >= 3 && /BOOTH/i.test(bits[1])) {
      var middle = bits.slice(2);
      if (middle.length && /^\d{1,2}:\d{2}\s*(?:AM|PM)$/i.test(middle[middle.length - 1])) {
        middle.pop();
      }
      named = middle.join(' - ').replace(/^THE\s+/i, '').trim();
    }
    if (!named) named = SCENE_NAMES[String((item && item.round) || '').toLowerCase()] || '';
    if (!named) {
      named = String((item && item.round) || 'Broadcast Segment')
        .replace(/[_-]+/g, ' ');
    }
    named = named.toLowerCase().replace(/(^|\s)([a-z])/g, function (_, gap, letter) {
      return gap + letter.toUpperCase();
    });
    return named.replace(/\bSfx\b/g, 'SFX').replace(/\bFm\b/g, 'FM');
  }

  function dressScene(node, item) {
    if (!node || !item) return;
    node.dataset.heading = String(item.text || '');
    node.dataset.at = String(Number(item.at || item.air_at) || '');
    node.dataset.round = String(item.round || '');
    node.replaceChildren();
    node.appendChild(make('time', 'sp-segment-time', sceneClock(item)));
    var words = make('span', 'sp-segment-words');
    words.appendChild(make('b', 'sp-segment-name', sceneName(item)));
    words.appendChild(make('small', 'sp-segment-place', 'Pine Box FM / The Booth'));
    node.appendChild(words);
    node.appendChild(make('span', 'sp-segment-count', ''));
    node.appendChild(make('span', 'sp-segment-state', ''));
  }

  /* The screenplay API has already placed each line against the ledger and
   * pinned unscripted feed events between cues. A scene's clock can run
   * backward after a recovered line, so it cannot sort this document. */
  function screenplayOrder(before, current) {
    return (before || []).concat(current || []);
  }

  /* Hollywood layout: each element type is its own block, and the CSS does
   * the indenting the way a script does - character centred over dialogue,
   * parentheticals tucked inside it, action full width. */
  function bindScriptOrder(order, items, asOf) {
    scriptOrder = order;
    elements = items;
    scriptAsOf = asOf;
    lineNodes.clear();
    sceneNodes.clear();
    segmentCounts = Object.create(null);
    order.forEach(function (node) {
      var item = node.pineItem || {};
      if (item.line) lineNodes.set(String(item.line), node);
      if (String(item.type || '') === 'scene' && item.seg) {
        sceneNodes.set(String(item.seg), node);
      }
      if (String(item.type || '') === 'dialogue' && item.seg) {
        var count = segmentCounts[String(item.seg)] || {lines: 0, seconds: 0};
        count.lines += 1;
        count.seconds += Number(item.seconds) || 0;
        segmentCounts[String(item.seg)] = count;
      }
    });
  }

  function paintScript(page, before) {
    var box = el('spScript');
    if (!box) return;
    var head = el('spScriptHead');
    if (head && page) {
      /* #1268: the count is of what is ON THE PAGE, both hours of it,
         because that is what the reader can scroll through. */
      var lines = (page.counts && page.counts.lines) || 0;
      var back = (before && before.counts && before.counts.lines) || 0;
      head.textContent = 'Pine Box FM / The Booth / ' + (page.title || 'the broadcast')
        + '  ·  ' + (lines + back) + ' lines'
        + (back ? '  (with the hour before)' : '')
        + (page.live ? '  ·  live' : '');
    }
    var atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    /* #1269: REBUILD ONLY WHAT CHANGED.
     *
     * "keep an eye on how it is jumping around"
     *
     * This used to replaceChildren() and re-append EVERY element on
     * every poll - twenty seconds, a few hundred nodes, and with the
     * hour before it now carried too (#1268) a few hundred more. Every
     * node the reader was looking at was destroyed and rebuilt, which
     * throws the scroll offset and drops the highlight (nowLineId was
     * cleared just below, unconditionally), so the page re-seated
     * itself three times a minute whether anything had changed or not.
     *
     * #1269 answered that with a longest-common-PREFIX compare, on the
     * reasoning that a script only ever grows at the end. It does not,
     * and #1273 below replaces it - see there for what moves the page
     * and what it measured. This note is kept only because the fault it
     * describes is still the right one to have been chasing.
     */
    /* #1273: KEPT, NOT REBUILT. The prefix match this replaces assumed
     * the script only grows at the end; measured on air it destroyed 240
     * nodes over eight polls, 238 of them identical content that had
     * merely moved. See the patch note for the three things that move
     * it. Nodes are keyed by the server's element id and kept. */
    if (paintedIn !== box) { scriptNodes.clear(); paintedIn = box; }
    markAuditAt = 0;
    markAuditNode = null;
    var anchor = scriptAnchor(box);
    var order = [];
    var wanted = Object.create(null);
    for (var i = 0; i < elements.length; i += 1) {
      var item = elements[i];
      var key = String(item.id || '') || ('ix:' + i);
      wanted[key] = 1;
      /* Everything the node's APPEARANCE depends on, so a line revised
         in place is re-dressed rather than rebuilt. */
      var print = String(item.text || '') + SEP + String(item.type || '')
        + SEP + String(item.aired || '') + SEP + (item.tinted ? '1' : '0')
        + SEP + String(item.round || '') + SEP + String(item.at || '')
        + SEP + (item.deleted ? 'D' : '');                        /* [#1200] */
      var node = scriptNodes.get(key);
      if (node && node.pinePrint !== print) {
        var lit = node.classList.contains('sp-now');
        var picked = node.classList.contains('picked');
        node.textContent = String(item.text || '');
        node.className = 'sp-el sp-' + String(item.type || 'action')
          + ((item.aired === 'prepared' || item.aired === 'withdrawn')   /* 2026-09-14: refused at hand-over - never aired */ ? ' pending' : '')
          + (item.tinted ? ' tinted' : '')
          + (lit ? ' sp-now' : '') + (picked ? ' picked' : '');
        if (item.deleted) node.classList.add('sp-deleted');        /* [#1200] */
        if (String(item.type || '') === 'scene') dressScene(node, item);
        node.pinePrint = print;
      }
      if (!node) {
        node = scriptBlock(item);
        node.pinePrint = print;
        scriptNodes.set(key, node);
      }
      /* #1303b: THE NODE CARRIES THE CURRENT ITEM.
         The click handler scriptBlock attaches closes over the item the
         node was BUILT with, and a re-dress does not refresh it. Anything
         reading the node later - the strip's hold, for one - should get
         what this line says now. */
      node.pineItem = item;
      // Keep evidence attributes in step with a keyed node's current item.
      ['line', 'seg', 'block', 'ord', 'round', 'at'].forEach(function (field) {
        if (item[field] !== undefined && item[field] !== null) node.dataset[field] = String(item[field]);
        else delete node.dataset[field];
      });
      order.push(node);
    }
    scriptNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode === box) held.remove();
      scriptNodes.delete(key);
    });
    bindScriptOrder(order, elements, scriptAsOf);
    /* Settle the final layout before measuring the reader's anchor. New
       rows in an already-finished segment arrive visible; restoring first
       and hiding them afterward makes the pane compensate twice in opposite
       directions. That was the remaining same-line jump in #1256-#1270. */
    segApply(false);
    scriptRestore(box, anchor);
    diagnosticDocument(box);
    ensureCaution();
    /* FOLLOWING BEATS STICKING TO THE END.
     * The live line sits wherever the conversation has got to, and the end
     * of the hour is usually well past it; scrolling to the bottom after
     * every repaint would drag the operator away from the line being said
     * twenty seconds after it arrived. */
    if (stick && atEnd && !(follow && nowLineId)) {
      moveScript('end', function (pane) { pane.scrollTop = pane.scrollHeight; });
    }
    /* #1273: THE MARK IS RE-ASSERTED, NOT MERELY REMEMBERED.
       #1269 asked whether a node with this id existed - not whether it
       still CARRIED the mark. A rebuilt node exists without .sp-now, so
       nowLineId stayed set, markNow returned at `id === nowLineId`, and
       the page showed no highlight at all until the station moved on.
       That is the operator's "highlighting incorrect segments". Keyed
       nodes make it rare; asking the right question makes it
       impossible. */
    /* [#1189] the marks are re-asserted on the keyed nodes, and the lit
       line is kept where the eye is if the repaint moved it. */
    placeMarks(lastDecision);
    keepLitInView('paint');
    tick();
  }

  /* ONE SCROLL CONTROLLER.
   *
   * "Use one scroll controller."
   *
   * There were four movers of this pane and only one of them declared
   * itself: the follow scroll in markNow stamped `selfScrollUntil`, while
   * the stick-to-end after a repaint, the reader's-place restore and the
   * tap-to-line jump all moved the box silently. Each of those fires the
   * pane's own scroll handler, which reads "the operator has scrolled by
   * hand" and switches following OFF - the page cancelling its own
   * following, which is the exact fault #1282 was fixed for once already.
   *
   * So every movement goes through here, declares a reason, and is
   * recorded for the incident report. A follow may not overrule a restore
   * in the same frame: the operator's place beats an automatic move. */
  var scrollOwner = '';
  var scrollAt = 0;
  var scrollLog = [];

  function moveScript(reason, apply) {
    var box = el('spScript');
    if (!box) return false;
    var now = Date.now();
    /* 2026-09-15 (#1183): this is one HALF of the rule, and the other
       half is in scriptRestore. A follow is held off while a restore is
       fresh, which stops a follow undoing a place-hold. The reverse -
       a restore landing in the middle of a follow's smooth animation -
       is what produced the operator's 3,407 px jump, and it cannot be
       caught here, because by the time a restore asks for the pane its
       drift has already been measured against a moving layout. It is
       refused where it is measured. */
    if (reason === 'follow' && scrollOwner === 'restore' && now - scrollAt < 80) {
      return false;
    }
    scrollOwner = reason;
    scrollAt = now;
    scrollLog.push({at: now, why: reason, top: Math.round(box.scrollTop)});
    if (scrollLog.length > 40) scrollLog.shift();
    /* Every automatic move is now one exact scrollTop assignment. Keep the
       event guard only long enough for that assignment's scroll event; a
       multi-second guard belonged to smooth animations and made the pane
       feel frozen after each line. */
    selfScrollUntil = now + 180;
    try { apply(box); } catch (err) { caughtNote('scroll:' + reason, err); }
    return true;
  }

  function seatLineNearest(pane, node) {
    if (!pane || !node || node.hidden) return false;
    var lip = pane.getBoundingClientRect();
    var seat = node.getBoundingClientRect();
    if (!(seat.height > 0 && lip.height > 0)) return false;
    var margin = Math.min(96, Math.max(20, lip.height * 0.14));
    var top = lip.top + margin;
    var bottom = lip.bottom - margin;
    var delta = 0;
    if (seat.height >= bottom - top) delta = seat.top - top;
    else if (seat.top < top) delta = seat.top - top;
    else if (seat.bottom > bottom) delta = seat.bottom - bottom;
    if (Math.abs(delta) <= 0.5) return false;
    pane.scrollTop = Math.max(0, pane.scrollTop + delta);
    return true;
  }

  /* #1273: HOLD THE READER'S PLACE ACROSS A REPAINT. Measure one row
     that is actually on screen before, find the SAME element after, and
     move the scroll by the difference - so an element inserted above the
     reader does not drag the page out from under them. Deliberately not
     derived from offsetTop; the sampler's commit records why that
     failed. */
  function scriptAnchor(box) {
    if (!box || box.scrollTop <= 4) return {pinned: true};
    var lip = box.getBoundingClientRect();
    /* #1277: while following the show, preserve the row the operator is
       actually reading. A repaint used the first visible row instead; when
       the server reindexed the active row, that unrelated anchor held still
       and the active row landed hundreds of pixels offscreen. */
    var live = box.querySelector('.sp-el.sp-now');
    if (live && !live.hidden) {
      var liveSeat = live.getBoundingClientRect();
      if (liveSeat.height > 0 && liveSeat.bottom > lip.top + 1
          && liveSeat.top < lip.bottom - 1) {
        return {node: live, was: liveSeat.top, active: true};
      }
    }
    for (var i = 0; i < box.children.length; i += 1) {
      if (!box.children[i].classList.contains('sp-el')) continue;
      var seat = box.children[i].getBoundingClientRect();
      if (seat.height <= 0) continue;
      if (seat.bottom <= lip.top + 1) continue;      /* scrolled off the top */
      return {node: box.children[i], was: seat.top};
    }
    return {pinned: true};
  }

  function scriptRestore(box, anchor) {
    if (!box || !anchor || anchor.pinned) return;
    var node = anchor.node;
    /* It left the page while it was being read. Leave the scroll alone:
       the browser's own anchoring has already chosen a neighbour. */
    if (!node || node.parentNode !== box) return;

    /* A same-turn follow already established the intended seat. Re-seat
       once against the settled layout instead of treating that deliberate
       movement as anchor drift. There is no animation left to race. */
    if (Date.now() < selfScrollUntil && scrollOwner === 'follow') {
      var lit = box.querySelector('.sp-el.sp-now');
      scrollLog.push({at: Date.now(), why: 'restore:skipped-mid-follow',
                      top: Math.round(box.scrollTop)});
      if (scrollLog.length > 40) scrollLog.shift();
      if (lit) {
        moveScript('follow', function (pane) { seatLineNearest(pane, lit); });
      }
      return;
    }

    var drift = node.getBoundingClientRect().top - anchor.was;
    if (Math.abs(drift) > 0.5) {
      moveScript('restore', function (pane) {
        pane.scrollTop = Math.max(0, pane.scrollTop + drift);
      });
    }
  }

  /* Put `order` into `box`, in that order, moving as little as possible.
     A node already in the right place costs one comparison; anything
     else is one insertBefore. */
  function stitchScript(box, order) {
    var cursor = box.firstChild;
    if (cursor && cursor.id === 'spCautionWrap') cursor = cursor.nextSibling;
    for (var i = 0; i < order.length; i += 1) {
      if (order[i] === cursor) { cursor = cursor.nextSibling; continue; }
      box.insertBefore(order[i], cursor);
    }
    /* #1289: the plan is not an element of the screenplay and must
       survive the stitch. It is kept, and kept last. */
    var plan = null;
    while (cursor) {
      var next = cursor.nextSibling;
      if (cursor.id === 'spPlan') { plan = cursor; }
      else if (cursor.id === 'spCautionWrap') { /* retained control */ }
      else { cursor.remove(); }
      cursor = next;
    }
    if (plan) box.appendChild(plan);
  }

  /* #1285: fold a finished segment, leave the one on air open.
   * The keyed list stays flat. Closed bodies leave the DOM but remain in
   * scriptOrder and the line index, ready for an immediate remount. */
  /* #1300: what each segment was last left as, so a repaint that
     re-asserts the same folds does not replay their motion. */
  var segWas = Object.create(null);
  var segFxTimer = 0;
  var FOLD_FX_MOST = 140;        /* beyond this a segment snaps */
  var FOLD_FX_MS = 260;

  function segApply(motion) {
    var box = el('spScript');
    if (!box) return;
    var moving = [], shutting = [], opening = [];      /* #1300 */
    var sceneOrder = [], sceneSeen = Object.create(null), displaySeg = '';
    for (var s = 0; s < scriptOrder.length; s += 1) {
      if (!/(^|\s)sp-scene(\s|$)/.test(String(scriptOrder[s].className || ''))) continue;
      var sid = scriptOrder[s].getAttribute('data-seg') || '';
      if (!sid || sceneSeen[sid]) continue;
      sceneSeen[sid] = 1;
      sceneOrder.push(sid);
      var sat = Number(scriptOrder[s].getAttribute('data-at') || 0);
      if (sat > 0 && sat <= scriptAsOf) displaySeg = sid;
    }
    if (liveSeg && sceneSeen[liveSeg]) displaySeg = liveSeg;
    var phase = Object.create(null), activeAt = sceneOrder.indexOf(displaySeg);
    for (var so = 0; so < sceneOrder.length; so += 1) {
      phase[sceneOrder[so]] = activeAt < 0 ? ''
        : so < activeAt ? 'past'
        : so === activeAt ? (liveSeg ? 'live' : 'current') : 'future';
    }
    /* #1294: EVERYTHING BEHIND THE AIR IS SHUT, NOT ONLY THE SEGMENT
     * IT JUST LEFT.
     *
     * segFollow folds the one the air walks out of, and `folded`
     * starts empty - so every segment that had already finished when
     * the page painted stayed open for ever. Measured: 0 to 3 shut of
     * 51-57 scenes, ~2,100 elements and ~62,000 px of scroll. The fold
     * worked; it was just never reached.
     *
     * DOM order is script order (the reconciler stitches the canonical
     * list), so "behind" is "before the first element of the live
     * segment". A hand still outranks this, and with nothing on air
     * nothing is folded. */
    if (displaySeg) {
      for (var key in phase) {
        if (phase[key] === 'past' && !byHand[key]) folded[key] = true;
      }
      folded[displaySeg] = false;
    }
    /* #1300b: WHICH SEGMENTS CHANGED, SETTLED BEFORE ANYTHING IS
     * WRITTEN.
     *
     * This used to be decided inside the loop below, against segWas,
     * which the same loop also updated - and a segment's SCENE HEADING
     * is its first element in DOM order. The heading is excluded from
     * the motion by `!head`, so it fell through and wrote segWas for
     * the whole segment; by the time the members were reached the
     * value they needed to compare against was already the new one,
     * and not one of them ever animated. Measured on the tablet: a
     * fold opening 51 members, `sp-fx` on zero of them.
     *
     * A loop must not both read and write the memo it is deciding by. */
    var segsNow = Object.create(null);
    var changed = Object.create(null);
    var segmentSizes = Object.create(null);
    for (var q = 0; q < scriptOrder.length; q += 1) {
      var qseg = scriptOrder[q].getAttribute('data-seg') || '';
      if (!qseg) continue;
      if (!/(^|\s)sp-scene(\s|$)/.test(String(scriptOrder[q].className || ''))) {
        segmentSizes[qseg] = (segmentSizes[qseg] || 0) + 1;
      }
      if (segsNow[qseg] !== undefined) continue;
      var qshut = !!(folded[qseg] && qseg !== displaySeg);
      segsNow[qseg] = qshut;
      if (segWas[qseg] !== undefined && segWas[qseg] !== qshut) changed[qseg] = 1;
    }

    /* Keep headings mounted. Retain a small closing scene for its fold
       transition, then detach it when the transition settles. */
    var mounted = scriptOrder.filter(function (node) {
      var seg = node.getAttribute('data-seg') || '';
      if (!seg || /(^|\s)sp-scene(\s|$)/.test(String(node.className || ''))) return true;
      return !segsNow[seg] || (motion && changed[seg]
        && segmentSizes[seg] <= FOLD_FX_MOST);
    });
    stitchScript(box, mounted);
    var all = box.querySelectorAll('.sp-el');

    for (var i = 0; i < all.length; i += 1) {
      var node = all[i];
      var seg = node.getAttribute('data-seg') || '';
      var head = /sp-scene/.test(node.className);
      var shut = !!(seg && folded[seg] && seg !== displaySeg);
      var stage = phase[seg] || '';
      node.classList.toggle('sp-segment-past', stage === 'past');
      node.classList.toggle('sp-segment-live', stage === 'live');
      node.classList.toggle('sp-segment-current', stage === 'current');
      node.classList.toggle('sp-segment-future', stage === 'future');
      node.classList.toggle('sp-segment-next', stage === 'future'
        && activeAt >= 0 && sceneOrder[activeAt + 1] === seg);
      /* The heading is how a folded segment is reopened, so it is the
         one thing that must never be hidden by its own fold. */
      /* #1300: and when this segment has just CHANGED state, it is
         shown changing rather than simply being different. */
      if (seg && motion && changed[seg] && !head
          && (moving.length < FOLD_FX_MOST)) {
        moving.push(node);
        if (shut) {
          /* Stays in layout while it collapses; hidden at the end. */
          node.hidden = false;
          node.classList.add('sp-fx');
          shutting.push(node);
        } else {
          node.hidden = false;
          node.classList.add('sp-fx', 'sp-gone');
          opening.push(node);
        }
        continue;                 /* segWas is settled after the loop */
      }
      if (node.classList.contains('sp-fx') || node.classList.contains('sp-gone')) {
        node.classList.remove('sp-fx', 'sp-gone');
      }
      node.hidden = shut && !head;
      if (head) {
        node.classList.toggle('sp-shut', shut);
        node.setAttribute('aria-expanded', shut ? 'false' : 'true');
        /* #1285b: what is inside, so a closed segment can be chosen
           without opening it. On an attribute and shown through
           ::after - the reconciler re-dresses a changed element with
           textContent and would wipe a child span every repaint. */
        /* #1428: WRITTEN ONLY WHEN IT CHANGES. Measured on the
           tablet, this wrote data-inside 177 times in eight seconds and
           3 of them were a change. Blink invalidates an element's style
           on the write, not on a difference, so the other 174 bought a
           style recalc each and nothing else. */
        var inside = '';
        if (shut) {
          var got = segCount(seg);
          inside = got
            ? ('  ▸ ' + got.lines + (got.lines === 1 ? ' line' : ' lines')
               + (got.seconds >= 1
                  ? '  ·  ' + Math.round(got.seconds) + 's' : ''))
            : '  ▸';
        }
        if (node.getAttribute('data-inside') !== inside) {
          node.setAttribute('data-inside', inside);
        }
        var summary = segCount(seg);
        var summaryText = summary
          ? (summary.lines + (summary.lines === 1 ? ' line' : ' lines')
             + (summary.seconds >= 1 ? ' / ' + Math.round(summary.seconds) + 's' : ''))
          : '';
        var count = node.querySelector('.sp-segment-count');
        if (count && count.textContent !== summaryText) count.textContent = summaryText;
        var state = node.querySelector('.sp-segment-state');
        var stateText = stage === 'live' ? 'ON AIR'
          : stage === 'current' ? 'CURRENT'
          : stage === 'past' ? 'AIRED'
          : node.classList.contains('sp-segment-next') ? 'UP NEXT'
          : stage === 'future' ? 'SCHEDULED' : '';
        if (state && state.textContent !== stateText) state.textContent = stateText;
      }
    }
    /* #1300b: and only now, once every element has been able to read
       the old value. */
    for (var done in segsNow) segWas[done] = segsNow[done];
    segSettle(shutting, opening);                            /* #1300 */
  }

  /* #1300: THE BATCH, FINISHED TOGETHER.
   *
   * One timer for the whole pass rather than one per node - a few
   * hundred timers is the kind of thing that makes a tablet stutter,
   * and they would all land in the same frame anyway.
   *
   * The close is only committed to `hidden` at the end, so a folded
   * segment still costs nothing in layout once it has gone; the open
   * only has to drop the class it started from. */
  function segSettle(shutting, opening) {
    if (!shutting.length && !opening.length) return;
    if (opening.length) {
      /* A frame with the start value on the node, or there is nothing
         for the transition to run FROM and it arrives instantly. */
      root.requestAnimationFrame(function () {
        for (var i = 0; i < opening.length; i += 1) {
          opening[i].classList.remove('sp-gone');
        }
      });
    }
    if (shutting.length) {
      root.requestAnimationFrame(function () {
        for (var i = 0; i < shutting.length; i += 1) {
          shutting[i].classList.add('sp-gone');
        }
      });
    }
    if (segFxTimer) root.clearTimeout(segFxTimer);
    segFxTimer = root.setTimeout(function () {
      segFxTimer = 0;
      for (var i = 0; i < shutting.length; i += 1) {
        shutting[i].hidden = true;
        shutting[i].classList.remove('sp-fx', 'sp-gone');
      }
      for (var k = 0; k < opening.length; k += 1) {
        opening[k].classList.remove('sp-fx', 'sp-gone');
      }
      segApply(false);
    }, FOLD_FX_MS + 40);
  }

  /* What is inside a fold, so it can be chosen without opening it. */
  function segCount(seg) {
    return seg ? segmentCounts[String(seg)] || null : null;
  }

  function segToggle(seg) {
    if (!seg) return;
    folded[seg] = !folded[seg];
    byHand[seg] = true;              /* the operator's choice outranks */
    segApply(true);                                          /* #1300 */
    foldSave();                                              /* #1294 */
  }

  /* #1294: THE READER'S PLACE OUTLIVES THE VIEW.
   *
   * The kiosk Activity is recreated roughly every five minutes - the
   * gallery writes the device wallpaper, systemui regenerates the
   * Material You overlays, and the resulting CONFIG_ASSETS_PATHS
   * (0x80000000) is not in MainActivity's configChanges mask, so the
   * WebView reloads. Seven relaunches in 33 minutes, each taking every
   * fold and the scroll position with it.
   *
   * localStorage, NOT sessionStorage: a relaunch is a new session and
   * would take session storage with it. Every read and write is
   * guarded - the accessor itself throws in some contexts - and a page
   * with nothing stored must render correctly, which here means the
   * folds simply start closed-behind-the-air as they now do anyway. */
  var FOLD_KEY = 'pine.script.folds.v1';

  function foldSave() {
    try {
      var box = el('spScript');
      root.localStorage.setItem(FOLD_KEY, JSON.stringify({
        folded: folded, byHand: byHand, liveSeg: liveSeg,
        top: box ? Math.round(box.scrollTop) : 0, at: Date.now()}));
    } catch (err) { /* storage blocked: the view still works */ }
  }

  var foldTop = -1;                  /* the scroll to restore, once */

  function foldLoad() {
    var held = null;
    try {
      held = JSON.parse(root.localStorage.getItem(FOLD_KEY) || 'null');
    } catch (err) { held = null; }
    if (!held || typeof held !== 'object') return;
    /* Stale beyond an hour is not this show any more. */
    if (Date.now() - Number(held.at || 0) > 3600000) return;
    if (held.folded && typeof held.folded === 'object') {
      for (var a in held.folded) folded[a] = !!held.folded[a];
    }
    if (held.byHand && typeof held.byHand === 'object') {
      for (var b in held.byHand) byHand[b] = !!held.byHand[b];
    }
    if (Number(held.top) > 0) foldTop = Number(held.top);
  }

  /* The air moved on: fold what it left, unless a hand opened it. */
  function segFollow(seg) {
    if (!seg || seg === liveSeg) return;
    var was = liveSeg;
    liveSeg = seg;
    if (was && !byHand[was]) folded[was] = true;
    folded[seg] = false;
    /* #1300: the hand-off the operator asked to SEE - the finished
       script shutting and the next one opening out. */
    var guard = foldGuardStart();                            /* [#1189] */
    segApply(true);
    foldSave();                                              /* #1294 */
    /* [#1189] the fold commits `hidden` at the end of its animation
       (segSettle); the reader's place is restored there, and the lit
       line is brought back if the reflow moved it out of view. */
    if (foldGuardTimer) root.clearTimeout(foldGuardTimer);
    foldGuardTimer = root.setTimeout(function () {
      foldGuardTimer = 0;
      foldGuardEnd('follow', guard);
      keepLitInView('fold');
    }, FOLD_FX_MS + 60);
  }

  /* #1289: THE HOUR AHEAD. /api/director?hour=N is already the hour
     as ordered entries, and a planned one carries its written turns. */
  function loadPlan(force) {
    if (planning) return;
    if (!force && Date.now() - planAt < PLAN_REST_MS) return;
    planning = true;
    var want = [api().get('/api/director?hour=0')
      .then(null, function () { return null; })];
    want.push(api().get('/api/director?hour=1')
      .then(null, function () { return null; }));
    want.push(api().get('/api/bank?minutes=120')
      .then(null, function () { return null; }));
    Promise.all(want).then(function (got) {
      var fresh = got.slice(0, 2).filter(Boolean);
      planning = false;
      /* #1289b: a failed read must not WIPE the running order. Both
         fetches swallow their own errors and return null, so a blip
         used to hand back an empty list, paintPlan cleared the node,
         and the hour ahead vanished until the next poll. Keep what we
         have unless something better arrived. */
      if (!fresh.length && !got[2]) return;
      if (fresh.length) {
        got.slice(0, 2).forEach(function (page, index) {
          if (page) planHours[index] = page;
        });
      }
      if (got[2] && Array.isArray(got[2].slots)) {
        bankPlan = got[2];
        bankFetchedAt = Date.now();
      }
      planAt = Date.now();
      paintPlan();
    }, function () { planning = false; });
  }

  function planRow(cls, text) {
    return make('div', 'sp-el ' + cls, String(text || ''));
  }

  /* #1294: the plan's own keyed nodes. paintPlan called
     box.replaceChildren() on a thirty-second timer - 509 nodes
     destroyed in one batch, ~1,012 a minute, and in one round of
     sixteen it wiped every visible plan row. This is the stitch
     paintScript has had since #1273, on the one pane that never got
     it. */
  var planNodes = new Map();
  var planIn = null;

  function planKeep(key, cls, text) {
    var print = cls + '\u0001' + text;
    var node = planNodes.get(key);
    if (node && node.pinePrint !== print) {
      node.className = cls;
      node.textContent = text;
      node.pinePrint = print;
    }
    if (!node) {
      node = make('div', cls, text);
      node.pinePrint = print;
      planNodes.set(key, node);
    }
    return node;
  }

  function bankSlotFor(entry, bank, used) {
    if (!bank || !Array.isArray(bank.slots) || !entry || !entry.slot_id) return null;
    var id = String(entry.slot_id);
    var kind = String(entry.kind || '');
    var sameRoad = function (value) {
      var road = String(value || '');
      return (road === 'banter_caller' ? 'caller'
        : road === 'bombshell' ? 'ad' : road) === kind;
    };
    var start = Number(entry.start) || 0;
    var best = null, distance = Infinity;
    bank.slots.forEach(function (slot, index) {
      if (used && used[index]) return;
      var commit = String(slot.commit_id || '');
      var slotId = commit.indexOf('current:') === 0
        ? commit.slice(commit.indexOf(':', 8) + 1)
        : commit.split('@')[0];
      if (slotId !== id || !sameRoad(slot.kind)) return;
      var gap = Math.abs((Number(bank.at) || 0)
        + (Number(slot.in_seconds) || 0) - start);
      if (start && gap > 300 && !(slot.current && entry.state === 'on air')) return;
      if (gap < distance) { best = {slot: slot, index: index}; distance = gap; }
    });
    return best;
  }

  function bankCoverageOf(bankSlot) {
    var coverage = bankSlot && bankSlot.coverage;
    return coverage && typeof coverage === 'object'
      && typeof coverage.ready === 'boolean' ? coverage : null;
  }

  function readinessBankDetail(bankSlot) {
    var coverage = bankCoverageOf(bankSlot);
    if (!coverage) return null;
    var seconds = function (value) {
      return Math.max(0, Number(value) || 0).toFixed(1) + 's';
    };
    var missing = function (value) { return Array.isArray(value) ? value : []; };
    var gaps = [];
    if (Number(coverage.script_short_seconds) > 1) {
      gaps.push(seconds(coverage.script_short_seconds) + ' script short');
    }
    if (Number(coverage.recording_short_seconds) > 1) {
      gaps.push(seconds(coverage.recording_short_seconds) + ' recording short');
    }
    if (Number(coverage.duration_short_seconds) > 1) {
      gaps.push(seconds(coverage.duration_short_seconds) + ' playable short');
    }
    if (missing(coverage.missing_roles).length) {
      gaps.push('Roles: ' + missing(coverage.missing_roles).join(', '));
    }
    if (Number(coverage.missing_turns) > 0) {
      gaps.push(Number(coverage.missing_turns) + ' turns missing');
    }
    if (Number(coverage.missing_events) > 0) {
      gaps.push(Number(coverage.missing_events) + ' events missing');
    }
    if (missing(coverage.missing_bookends).length) {
      gaps.push('Write bookends: ' + missing(coverage.missing_bookends).join(', '));
    }
    if (missing(coverage.missing_recorded_bookends).length) {
      gaps.push('Record bookends: '
        + missing(coverage.missing_recorded_bookends).join(', '));
    }
    var tasks = Array.isArray(bankSlot.tasks) ? bankSlot.tasks.map(function (task) {
      task = task || {};
      var room = String(task.room || '').trim();
      if (!room) return null;
      var ready = task.ready === true || task.state === 'ready';
      return {room: room, ready: ready, wantSeconds: Math.max(0,
        Number(task.want_seconds) || 0), dueIn: Number(task.prepare_by_in_seconds)};
    }).filter(Boolean) : [];
    return {ready: coverage.ready, facts: [
      seconds(coverage.scripted_seconds) + ' scripted',
      seconds(coverage.recorded_seconds) + ' recorded',
      seconds(coverage.covered_seconds) + '/'
        + seconds(coverage.target_seconds) + ' playable coverage'
    ], gaps: gaps, tasks: tasks};
  }

  function readinessCardCoverage(model) {
    var coverage = model.coverage;
    if (!coverage) return model.lines + '/' + model.targetLines + ' lines / '
      + Math.round(model.readySeconds) + '/' + Math.round(model.targetSeconds) + 's';
    return model.lines + '/' + model.targetLines + ' lines / '
      + Math.round(Number(coverage.covered_seconds) || 0) + '/'
      + Math.round(Number(coverage.target_seconds) || 0) + 's measured'
      + (Number(coverage.short_seconds) > 1
        ? ' / ' + Math.round(Number(coverage.short_seconds)) + 's short' : '');
  }

  /* A compact, honest model for the preparation desk. The director owns
   * the schedule and orchestration verdict; bank coverage supplies a second,
   * measured production verdict when available. */
  function readinessOf(entry, bankSlot, now) {
    entry = entry || {};
    var script = entry.script || {};
    var orchestration = entry.orchestration || {};
    var review = entry.review || {};
    var suppliedStages = orchestration.stages || {};
    var bound = Array.isArray(script.turns) ? script.turns : [];
    var drafts = Array.isArray(script.draft_turns) ? script.draft_turns : [];
    var variants = Array.isArray(script.draft_variants) ? script.draft_variants : [];
    var variant = !bound.length && variants.find(function (item) {
      return String((item || {}).id || '') === String(script.selected_candidate || '');
    }) || (!bound.length && variants[0]) || null;
    var turns = bound.length ? bound : (drafts.length ? drafts
      : (variant && Array.isArray(variant.turns) ? variant.turns : []));
    var performancePlan = scriptPerformances(bound.length || drafts.length
      ? script : (variant || script));
    var start = Number(entry.start) || 0;
    var deadline = Number(entry.deadline) || 0;
    var have = orchestration.have || {};
    var target = orchestration.target || {};
    var readySeconds = String(script.state || '') === 'bound'
      ? Math.max(0, Number(have.seconds !== undefined ? have.seconds : script.seconds) || 0) : 0;
    var targetSeconds = target.seconds !== undefined && isFinite(Number(target.seconds))
      ? Math.max(0, Number(target.seconds))
      : Math.max(0, (Number(entry.minutes) || 0) * 60);
    var short = (orchestration.short || {}).seconds;
    var shortSeconds = Math.max(0, short !== undefined && short !== null
      ? Number(short) || 0 : targetSeconds - readySeconds);
    var stages = {
      written: typeof suppliedStages.written === 'boolean'
        ? suppliedStages.written : turns.length > 0,
      reviewed: typeof suppliedStages.reviewed === 'boolean'
        ? suppliedStages.reviewed : review.approved === true,
      recorded: typeof suppliedStages.recorded === 'boolean'
        ? suppliedStages.recorded : readySeconds > 0,
      scheduled: typeof suppliedStages.scheduled === 'boolean'
        ? suppliedStages.scheduled : start > 0,
      executed: typeof suppliedStages.executed === 'boolean'
        ? suppliedStages.executed : String(entry.state || '') === 'aired'
    };
    var state = String(entry.state || 'planned');
    var live = state === 'on air';
    var status = String(orchestration.status || '');
    var directorReady = stages.written && stages.reviewed && stages.recorded
      && stages.scheduled && (status ? status === 'ready' : shortSeconds <= 0.5);
    var coverage = bankCoverageOf(bankSlot);
    var ready = directorReady && (!coverage || coverage.ready);
    var key = String(entry.occurrence || entry.slot_id || entry.ordinal || start);
    return {
      key: key, entry: entry, bank: bankSlot || null, coverage: coverage,
      turns: turns,
      performances: performancePlan.rows, candidates: performancePlan.candidates,
      performanceSeconds: performancePlan.seconds,
      draftOnly: !bound.length && turns.length > 0,
      label: String(entry.label || entry.kind || 'Segment'),
      kind: String(entry.kind || ''), state: state, live: !!live,
      status: !stages.reviewed && status === 'ready' ? 'awaiting-review'
        : (directorReady && coverage && !coverage.ready ? 'contract-incomplete'
          : (status || (ready ? 'ready' : 'needs-work'))), ready: !!ready,
      start: start, deadline: deadline, startsIn: start ? start - now : null,
      stages: stages, review: review, needs: Array.isArray(orchestration.needs)
        ? orchestration.needs.slice() : [],
      lines: have.lines !== undefined ? Number(have.lines) || 0 : turns.length,
      targetLines: target.lines !== undefined ? Number(target.lines) || 0 : turns.length,
      events: Number(have.events) || 0,
      targetEvents: Number(target.events) || 0,
      readySeconds: readySeconds, targetSeconds: targetSeconds,
      shortSeconds: shortSeconds
    };
  }

  function readinessQueue(hours, bank, now, limit) {
    var rows = [], seenKeys = Object.create(null);
    (hours || []).forEach(function (page, hourIndex) {
      ((page && page.entries) || []).forEach(function (entry, ordinal) {
        var state = String((entry && entry.state) || '');
        if (state === 'aired' || state.indexOf('went by') === 0) return;
        var key = String((entry && entry.occurrence) || [
          String((page && page.hour) || ''), String((entry && entry.start) || ''),
          String((entry && entry.slot_id) || ''), ordinal].join(':'));
        if (seenKeys[key]) return;
        seenKeys[key] = true;
        rows.push({entry: entry || {}, hourIndex: hourIndex, ordinal: ordinal,
          key: key});
      });
    });
    rows.sort(function (a, b) {
      var left = Number(a.entry.start) || 0;
      var right = Number(b.entry.start) || 0;
      if (!left && right) return 1;
      if (left && !right) return -1;
      return left === right
        ? (a.hourIndex - b.hourIndex || a.ordinal - b.ordinal) : left - right;
    });
    var used = Object.create(null);
    var out = rows.map(function (row) {
      var hit = bankSlotFor(row.entry, bank, used);
      if (hit) used[hit.index] = 1;
      var item = readinessOf(row.entry, hit && hit.slot, now);
      item.key = row.key;
      return item;
    });
    var cap = Math.max(1, Number(limit) || 8);
    return out.slice(0, cap);
  }

  function liveScriptEvents(list) {
    var out = [], speaker = '', segment = '';
    (list || []).forEach(function (item) {
      item = item || {};
      var nextSegment = String(item.seg || '');
      if (nextSegment && nextSegment !== segment) {
        segment = nextSegment;
        speaker = '';
      }
      if (String(item.type || '') === 'character') {
        speaker = String(item.text || '').trim();
        return;
      }
      if (!item.line) return;
      out.push({id: String(item.line), text: String(item.text || ''),
        speaker: String(item.name || item.who || speaker || ''),
        kind: String(item.kind || item.round || item.type || 'event'),
        type: String(item.type || 'event')});
    });
    return out;
  }

  function feedScriptEvents(list) {
    return (list || []).filter(function (item) { return item && item.id; })
      .map(function (item, index) {
        return {id: String(item.id), text: String(item.text || ''),
          speaker: String(item.name || item.who || ''),
          kind: String(item.kind || 'event'), type: String(item.kind || 'event'),
          at: Number(item.air_at || item.ts) || 0, index: index};
      }).sort(function (a, b) { return a.at - b.at || a.index - b.index; });
  }

  /* Prefer the sounding burst because it is the exact playout order and
   * includes board/SFX events. Fall back to screenplay order when the
   * current event is a single clip outside that burst. */
  function liveCueWindow(row, stream, list, radius, feedRows) {
    var id = String((row && row.id) || '');
    if (!id) return [];
    var streamRows = Array.isArray(stream && stream.rows) ? stream.rows : [];
    var source = streamRows.map(function (item) {
      return {id: String(item.id || ''), text: String(item.text || ''),
        speaker: String(item.name || item.speaker || item.who || ''),
        kind: String(item.kind || 'event'), type: String(item.kind || 'event')};
    });
    var at = source.findIndex(function (item) { return item.id === id; });
    if (at < 0) {
      source = feedScriptEvents(feedRows);
      at = source.findIndex(function (item) { return item.id === id; });
    }
    if (at < 0) {
      source = liveScriptEvents(list);
      at = source.findIndex(function (item) { return item.id === id; });
    }
    if (at < 0) {
      source = [{id: id, text: String((row && row.text) || ''),
        speaker: String((row && row.speaker) || ''), kind: 'event', type: 'event'}];
      at = 0;
    }
    var reach = Math.max(1, Number(radius) || 2);
    return source.slice(Math.max(0, at - reach), at + reach + 1)
      .map(function (item, index, windowRows) {
        var copy = Object.assign({}, item);
        copy.current = item.id === id;
        copy.relative = index - windowRows.findIndex(function (one) { return one.id === id; });
        if (copy.current) {
          if (!copy.text && row && row.text) copy.text = String(row.text);
          if (!copy.speaker && row && row.speaker) copy.speaker = String(row.speaker);
        }
        return copy;
      });
  }

  function bankSlotText(slot) {
    return 'BANK  |  ' + (Number(slot.ready_seconds) || 0).toFixed(1)
      + 's rendered  |  ' + (Number(slot.written_only_seconds) || 0).toFixed(1)
      + 's written only  |  ' + (Number(slot.short_seconds) || 0).toFixed(1)
      + 's missing  |  ' + ((slot.items || []).length) + ' stock item(s)';
  }

  function planReviewLabel(entry) {
    var script = entry.script || {};
    if (!(script.turns || []).length && !(script.draft_turns || []).length) {
      return 'No script allocated to this slot';
    }
    var review = entry.review || {};
    if (review.approved) return 'Script approved';
    if (review.seen) return 'Seen, awaiting approval';
    return 'Script needs review';
  }

  function readinessWhen(item) {
    if (item.live) return 'ON AIR';
    if (item.startsIn === null || !isFinite(item.startsIn)) return '--:--';
    if (item.startsIn <= 0) return 'DUE NOW';
    if (item.startsIn < 60) return Math.ceil(item.startsIn) + 's';
    if (item.startsIn < 3600) return Math.ceil(item.startsIn / 60) + 'm';
    return itinClock(item.start) || '--:--';
  }

  function readinessStage(name, done, full) {
    var label = {written: 'Written', reviewed: 'Reviewed', recorded: 'Recorded',
      scheduled: 'Scheduled', executed: 'Executed'}[name] || name;
    var node = make('span', 'sp-ready-stage', full ? label : label.charAt(0));
    node.dataset.stage = name;
    node.dataset.done = done ? 'true' : 'false';
    node.title = label + ': ' + (done ? 'complete' : 'not complete');
    node.setAttribute('aria-label', node.title);
    return node;
  }

  function readinessLine(turn, index) {
    var row = make('div', 'sp-ready-line');
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    row.title = 'Inspect or edit this prepared line';
    row.dataset.performance = String(turnPerformanceIndex(turn));
    row.dataset.candidateIndex = String(turnCandidateIndex(turn, index));
    row.appendChild(make('b', '', String(turn.who || turn.seat || turn.kind || 'Event')));
    row.appendChild(make('span', '', String(turn.text || '(assembly cue)')));
    return row;
  }

  function newsOptionsFor(model) {
    var slotId = String((model.entry || {}).slot_id || '');
    if (newsChoiceState && newsChoiceState.slotId === slotId) return newsChoiceState;
    var state = {slotId: slotId, status: slotId ? 'loading' : 'error',
      options: [], selectedUrl: '', draftUrl: '', error: slotId ? '' : 'This news slot has no ID.'};
    newsChoiceState = state;
    if (!slotId) return state;
    Promise.resolve().then(function () {
      return api().get('/api/news/options?slot_id=' + encodeURIComponent(slotId));
    }).then(function (got) {
      if (!got || !Array.isArray(got.options)) throw new Error('News choices are unavailable.');
      if (newsChoiceState !== state) return;
      var seen = Object.create(null);
      state.options = got.options.filter(function (option) {
        var url = option && String(option.url || '').trim();
        if (!url || seen[url]) return false;
        seen[url] = true;
        return true;
      });
      state.selectedUrl = String(got.selected_url || '');
      state.draftUrl = state.selectedUrl;
      state.status = 'ready';
      newsChoicesRepaint(model, state);
    }).catch(function (err) {
      if (newsChoiceState !== state) return;
      state.status = 'error';
      state.error = rejectionError(err);
      newsChoicesRepaint(model, state);
    });
    return state;
  }

  function newsChoicesRepaint(model, state) {
    var detail = el('spReadinessDetail');
    if (newsChoiceState === state && detail && !detail.hidden
      && detail.dataset.key === model.key) paintReadinessDetail(model);
  }

  function readinessNewsChoices(model) {
    var state = newsOptionsFor(model);
    var section = make('section', 'sp-ready-news');
    section.appendChild(make('h3', '', 'News story'));
    if (state.status === 'loading') {
      var loading = make('p', 'sp-ready-news-message', 'Loading story choices...');
      loading.setAttribute('role', 'status');
      section.appendChild(loading);
      return section;
    }
    if (state.status === 'error') {
      var failed = make('p', 'sp-ready-news-error', state.error);
      failed.setAttribute('role', 'alert');
      section.appendChild(failed);
      if (state.slotId) {
        var retry = make('button', 'sp-planact', 'Retry stories');
        retry.type = 'button';
        retry.addEventListener('click', function () {
          newsChoiceState = null;
          newsChoicesRepaint(model, newsOptionsFor(model));
        });
        section.appendChild(retry);
      }
      return section;
    }
    if (!state.options.length) {
      section.appendChild(make('p', 'sp-ready-news-message', 'No story choices available.'));
      return section;
    }
    var group = make('fieldset', 'sp-ready-news-group');
    group.appendChild(make('legend', '', 'Choose a story for this segment'));
    var selected = state.options.find(function (option) {
      return String(option.url) === state.selectedUrl;
    });
    var current = make('p', 'sp-ready-news-selection', selected
      ? 'Selected: ' + String(selected.title || selected.url)
      : (state.selectedUrl ? 'A different story is currently selected.' : 'No story selected.'));
    current.setAttribute('role', 'status');
    group.appendChild(current);
    var choose = make('button', 'sp-planact sp-ready-news-choose', 'Choose story');
    choose.type = 'button';
    choose.disabled = !state.draftUrl || state.draftUrl === state.selectedUrl
      || state.status === 'saving';
    state.options.forEach(function (option) {
      var url = String(option.url);
      var row = make('label', 'sp-ready-news-option');
      row.dataset.selected = url === state.selectedUrl ? 'true' : 'false';
      var radio = make('input', '');
      radio.type = 'radio';
      radio.name = 'sp-ready-news-' + state.slotId;
      radio.value = url;
      radio.checked = url === state.draftUrl;
      radio.disabled = state.status === 'saving';
      radio.addEventListener('change', function () {
        if (!radio.checked) return;
        state.draftUrl = url;
        choose.disabled = url === state.selectedUrl;
      });
      row.appendChild(radio);
      var words = make('span', 'sp-ready-news-copy');
      words.appendChild(make('b', '', String(option.title || url)));
      words.appendChild(make('span', 'sp-ready-news-meta', [option.source,
        option.availability].filter(Boolean).map(String).join(' / ')));
      if (option.excerpt) words.appendChild(make('span', 'sp-ready-news-excerpt',
        String(option.excerpt)));
      row.appendChild(words);
      group.appendChild(row);
    });
    section.appendChild(group);
    var actions = make('div', 'sp-ready-news-actions');
    choose.addEventListener('click', function () {
      if (!state.draftUrl || state.draftUrl === state.selectedUrl
        || state.status === 'saving') return;
      var url = state.draftUrl;
      state.status = 'saving';
      state.error = '';
      newsChoicesRepaint(model, state);
      Promise.resolve().then(function () {
        return api().post('/api/news/choice', {slot_id: state.slotId, url: url});
      }).then(function (got) {
        if (got && got.ok === false) throw new Error(String(got.detail || got.say || 'Story was not selected.'));
        if (newsChoiceState !== state) return;
        state.selectedUrl = url;
        state.draftUrl = url;
        state.status = 'ready';
        newsChoicesRepaint(model, state);
        loadPlan(true);
        loadScreenplay(true);
      }).catch(function (err) {
        if (newsChoiceState !== state) return;
        state.status = 'ready';
        state.error = rejectionError(err);
        newsChoicesRepaint(model, state);
      });
    });
    actions.appendChild(choose);
    section.appendChild(actions);
    if (state.error) {
      var error = make('p', 'sp-ready-news-error', state.error);
      error.setAttribute('role', 'alert');
      section.appendChild(error);
    }
    return section;
  }

  function paintReadinessDetail(model) {
    var detail = el('spReadinessDetail');
    if (!detail) return;
    var scrollTop = detail.scrollTop;
    detail.replaceChildren();
    detail.hidden = !model;
    if (!model) return;
    detail.dataset.key = model.key;
    var top = make('div', 'sp-ready-detail-head');
    var title = make('div', 'sp-ready-detail-title');
    title.appendChild(make('b', '', model.label));
    title.appendChild(make('span', '', (itinClock(model.start) || 'Unscheduled')
      + ' / ' + String(model.status || model.state).replace(/[-_]+/g, ' ')
      + (model.draftOnly ? ' / draft, not allocated' : '')));
    top.appendChild(title);
    var close = make('button', 'sp-ready-close', 'Close');
    close.type = 'button';
    close.addEventListener('click', function () {
      readinessPick = ''; readinessPrint = ''; paintReadiness();
    });
    top.appendChild(close);
    detail.appendChild(top);

    var facts = make('div', 'sp-ready-facts');
    facts.appendChild(make('span', '', model.lines + '/' + model.targetLines + ' lines'));
    facts.appendChild(make('span', '', model.events + '/' + model.targetEvents + ' events'));
    facts.appendChild(make('span', '', model.readySeconds.toFixed(1) + '/'
      + model.targetSeconds.toFixed(1) + 's recorded'));
    if (model.bank) facts.appendChild(make('span', '',
      (Number(model.bank.ready_seconds) || 0).toFixed(1) + 's banked stock'));
    facts.appendChild(make('span', '', model.performances.length
      + (model.performances.length === 1 ? ' performance' : ' performances')));
    detail.appendChild(facts);
    var stages = make('div', 'sp-ready-stages');
    Object.keys(model.stages).forEach(function (name) {
      stages.appendChild(readinessStage(name, model.stages[name], true));
    });
    detail.appendChild(stages);
    if (model.needs.length) {
      var needs = make('ul', 'sp-ready-needs');
      model.needs.forEach(function (need) {
        needs.appendChild(make('li', '', String(need)));
      });
      detail.appendChild(needs);
    }

    var bankDetail = readinessBankDetail(model.bank);
    if (bankDetail) {
      var contract = make('section', 'sp-ready-contract');
      contract.appendChild(make('h3', '', bankDetail.ready
        ? 'Measured contract ready' : 'Measured contract incomplete'));
      var measured = make('div', 'sp-ready-contract-facts');
      bankDetail.facts.forEach(function (fact) {
        measured.appendChild(make('span', '', fact));
      });
      contract.appendChild(measured);
      if (bankDetail.gaps.length) {
        var gaps = make('ul', 'sp-ready-contract-gaps');
        bankDetail.gaps.forEach(function (gap) {
          gaps.appendChild(make('li', '', gap));
        });
        contract.appendChild(gaps);
      }
      if (bankDetail.tasks.length) {
        var rooms = make('div', 'sp-ready-rooms');
        bankDetail.tasks.forEach(function (task) {
          var row = make('div', 'sp-ready-room');
          row.dataset.ready = task.ready ? 'true' : 'false';
          row.appendChild(make('b', '', task.room));
          var duty = task.ready ? 'clear' : 'owed'
            + (task.wantSeconds > 0 ? ' / ' + task.wantSeconds.toFixed(1) + 's' : '');
          if (!task.ready && isFinite(task.dueIn)) {
            duty += task.dueIn <= 0 ? ' / due now'
              : ' / due in ' + Math.ceil(task.dueIn / 60) + 'm';
          }
          row.appendChild(make('span', '', duty));
          rooms.appendChild(row);
        });
        contract.appendChild(rooms);
      }
      detail.appendChild(contract);
    }

    var briefRows = [
      ['Prompt', model.entry.prompt], ['Notes', model.entry.notes],
      ['Topic', (model.entry.script || {}).topic]
    ].filter(function (row) { return String(row[1] || '').trim(); });
    var direction = model.entry.direction || {};
    ['standing', 'next'].forEach(function (key) {
      (Array.isArray(direction[key]) ? direction[key] : []).forEach(function (item) {
        if (item && item.text) briefRows.push([
          key === 'next' ? 'Next direction' : 'Standing direction', item.text]);
      });
    });
    (Array.isArray(model.entry.beats) ? model.entry.beats : []).forEach(function (beat) {
      var words = typeof beat === 'string' ? beat
        : (beat && (beat.text || beat.label || beat.title));
      if (words) briefRows.push(['Beat', words]);
    });
    if (briefRows.length) {
      var brief = make('section', 'sp-ready-brief');
      brief.appendChild(make('h3', '', 'Preparation brief'));
      briefRows.forEach(function (row) {
        var fact = make('div', 'sp-ready-brief-row');
        fact.appendChild(make('b', '', row[0]));
        fact.appendChild(make('span', '', String(row[1])));
        brief.appendChild(fact);
      });
      detail.appendChild(brief);
    }
    if (model.kind === 'news') detail.appendChild(readinessNewsChoices(model));
    if (model.bank && Array.isArray(model.bank.items) && model.bank.items.length) {
      var stock = make('section', 'sp-ready-stock');
      stock.appendChild(make('h3', '', 'Banked stock'));
      model.bank.items.forEach(function (item) {
        stock.appendChild(make('div', '', String(item.label || item.title
          || item.text || item.sid || 'Prepared item')));
      });
      detail.appendChild(stock);
    }

    var script = make('div', 'sp-ready-script');
    var grouped = Object.create(null);
    model.turns.forEach(function (turn, index) {
      var pi = turnPerformanceIndex(turn);
      if (!grouped[pi]) grouped[pi] = [];
      grouped[pi].push({turn: turn, index: index});
    });
    var performanceRows = model.performances.length ? model.performances
      : Object.keys(grouped).map(function (key) {
        return {index: Number(key), candidate: '', seconds: 0,
          turns: grouped[key].length};
      });
    performanceRows.forEach(function (performance) {
      var section = make('section', 'sp-ready-performance');
      var head = make('div', 'sp-ready-performance-head');
      head.appendChild(make('b', '', 'Performance ' + (performance.index + 1)));
      head.appendChild(make('span', '', [performance.candidate,
        performance.turns ? performance.turns + ' turns' : '',
        performance.seconds ? Number(performance.seconds).toFixed(1) + 's' : '']
        .filter(Boolean).join(' / ')));
      section.appendChild(head);
      (grouped[performance.index] || []).forEach(function (line) {
        var node = readinessLine(line.turn, line.index);
        function open() {
          itinTurnOpen(model.entry, line.turn, line.index, function () { loadPlan(true); });
        }
        node.addEventListener('click', open);
        node.addEventListener('keydown', function (event) {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          open();
        });
        section.appendChild(node);
      });
      script.appendChild(section);
    });
    if (!model.turns.length) {
      script.appendChild(make('p', 'sp-ready-empty',
        'No prepared lines are allocated to this segment.'));
    }
    detail.appendChild(script);

    var actions = make('div', 'sp-ready-actions');
    var message = make('span', 'sp-ready-result', '');
    message.setAttribute('role', 'status');
    if (model.entry.occurrence && model.turns.length && !model.review.approved) {
      var approve = make('button', 'sp-planact sp-ready-approve', 'Approve script');
      approve.type = 'button';
      approve.addEventListener('click', function () {
        approve.disabled = true; message.textContent = 'Approving...';
        api().post('/api/director/segment/'
          + encodeURIComponent(model.entry.occurrence) + '/approve',
          {who: 'operator'}).then(function (got) {
          model.entry.review = Object.assign({}, model.entry.review, {approved: true});
          message.textContent = String((got && got.say) || 'Script approved.');
          readinessPrint = ''; paintReadiness(); loadPlan(true);
        }, function (err) {
          approve.disabled = false;
          message.textContent = String((err && err.message) || err);
        });
      });
      actions.appendChild(approve);
    }
    if ((model.entry.orchestration || {}).preparable) {
      var prepare = make('button', 'sp-planact', model.ready
        ? 'Prepare another' : 'Prepare segment');
      prepare.type = 'button'; prepare.dataset.kind = model.kind;
      prepare.addEventListener('click', function () { planPrepare(prepare); });
      actions.appendChild(prepare);
    }
    var air = make('button', 'sp-planact', 'Return to air');
    air.type = 'button';
    air.addEventListener('click', function () {
      readinessPick = ''; readinessPrint = ''; paintReadiness();
      resumeAirFollow('readiness desk');
    });
    actions.appendChild(air);
    actions.appendChild(message);
    detail.appendChild(actions);
    detail.scrollTop = scrollTop;
  }

  function paintReadiness() {
    var rail = el('spReadiness');
    var track = el('spReadinessTrack');
    var summary = el('spReadinessSummary');
    if (!rail || !track || !summary) return;
    var bank = bankPlan && Date.now() - bankFetchedAt < 180000 ? bankPlan : null;
    var queue = readinessQueue(planHours, bank, Date.now() / 1000, 8);
    if (readinessPick && !queue.some(function (item) { return item.key === readinessPick; })) {
      readinessPick = '';
    }
    var print = JSON.stringify(queue.map(function (item) {
      return [item.key, item.label, item.kind, item.start, item.deadline,
        item.state, item.status, item.ready, item.review.approved,
        item.lines, item.targetLines, item.events, item.targetEvents,
        item.readySeconds, item.targetSeconds, item.shortSeconds,
        item.stages, item.needs, item.entry.orchestration && item.entry.orchestration.preparable,
        item.performances, item.entry.prompt, item.entry.notes,
        item.entry.direction, item.entry.beats, item.bank,
        item.turns.map(function (turn) {
          return [turn.text, turn.who, turn.seat, turn.candidate,
            turnCandidateIndex(turn), turnPerformanceIndex(turn)];
        })];
    })) + '|' + readinessPick;
    if (print === readinessPrint) {
      queue.forEach(function (item) {
        var card = Array.prototype.find.call(track.children, function (node) {
          return node.dataset.key === item.key;
        });
        var clock = card && card.querySelector('time');
        if (clock) clock.textContent = readinessWhen(item);
      });
      return;
    }
    readinessPrint = print;
    var readyCount = queue.filter(function (item) { return item.ready; }).length;
    summary.textContent = queue.length ? readyCount + ' ready / '
      + (queue.length - readyCount) + ' need attention' : 'No upcoming entries';
    var trackLeft = track.scrollLeft;
    var focused = document.activeElement && document.activeElement.dataset
      && document.activeElement.dataset.key;
    track.replaceChildren();
    queue.forEach(function (item) {
      var card = make('button', 'sp-ready-card', '');
      card.type = 'button'; card.dataset.key = item.key;
      card.dataset.status = item.live ? 'live' : (item.ready ? 'ready' : 'attention');
      card.setAttribute('aria-expanded', readinessPick === item.key ? 'true' : 'false');
      var top = make('span', 'sp-ready-card-top');
      top.appendChild(make('time', '', readinessWhen(item)));
      top.appendChild(make('b', '', item.label));
      card.appendChild(top);
      card.appendChild(make('span', 'sp-ready-card-state',
        item.live ? 'on air' : String(item.status).replace(/[-_]+/g, ' ')));
      card.appendChild(make('span', 'sp-ready-card-coverage',
        readinessCardCoverage(item)));
      var marks = make('span', 'sp-ready-card-stages');
      Object.keys(item.stages).forEach(function (name) {
        marks.appendChild(readinessStage(name, item.stages[name]));
      });
      card.appendChild(marks);
      card.title = 'Review the script and preparation for ' + item.label;
      card.addEventListener('click', function () {
        readinessPick = readinessPick === item.key ? '' : item.key;
        readinessPrint = ''; paintReadiness();
      });
      track.appendChild(card);
    });
    track.scrollLeft = trackLeft;
    if (focused) {
      var replacement = Array.prototype.find.call(track.children, function (node) {
        return node.dataset.key === focused;
      });
      if (replacement) replacement.focus({preventScroll: true});
    }
    paintReadinessDetail(queue.find(function (item) { return item.key === readinessPick; }) || null);
  }

  function paintLiveCueWindow(row) {
    var strip = el('spLiveSequence');
    if (!strip) return;
    var feedRows = [];
    try {
      feedRows = root.PineStationFeed && root.PineStationFeed.rows
        ? root.PineStationFeed.rows() : [];
    } catch (err) { feedRows = []; }
    var rows = liveCueWindow(row, liveStream, elements, 2, feedRows);
    var print = rows.map(function (item) {
      return item.id + ':' + (item.current ? '1' : '0') + ':' + item.text;
    }).join('|');
    if (print === liveCuePrint) return;
    liveCuePrint = print;
    strip.replaceChildren();
    strip.hidden = !rows.length;
    if (bandManager) bandManager.refresh();
    var currentCue = null;
    rows.forEach(function (item) {
      var button = make('button', 'sp-live-cue', '');
      button.type = 'button'; button.dataset.line = item.id;
      button.dataset.kind = item.kind || item.type;
      if (item.current) {
        button.setAttribute('aria-current', 'step');
        currentCue = button;
      }
      var relation = item.current ? 'ON AIR' : (item.relative < 0 ? 'PREVIOUS' : 'NEXT');
      button.appendChild(make('em', '', relation));
      button.appendChild(make('b', '', item.speaker || item.kind || 'Event'));
      button.appendChild(make('span', '', item.text || 'Scripted event'));
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        if (item.current) resumeAirFollow('live cue window', item.id);
        else if (lineNodes.has(String(item.id)) || lineNode(item.id)) jumpToLine(item.id);
        else loadScreenplay(true);
      });
      strip.appendChild(button);
    });
    if (currentCue) {
      strip.scrollLeft = Math.max(0, currentCue.offsetLeft - strip.offsetLeft
        - (strip.clientWidth - currentCue.offsetWidth) / 2);
    }
  }

  function planCommand(key, label, title, run) {
    var button = planNodes.get(key);
    if (!button) {
      button = make('button', 'sp-planact', label);
      button.type = 'button';
      planNodes.set(key, button);
    }
    if (button.textContent !== label && !button.disabled) button.textContent = label;
    button.title = title;
    button.pineKey = key;
    button.onclick = run;
    return button;
  }

  function planPrepare(button) {
    button.disabled = true;
    button.textContent = 'Queuing...';
    api().post('/api/pantry/commission', {
      kind: String(button.dataset.kind || ''), count: 1
    }).then(function () {
      button.textContent = 'Queued';
      setTimeout(function () {
        button.disabled = false;
        loadPlan(true);
      }, 2200);
    }, function (err) {
      button.disabled = false;
      button.textContent = 'Retry preparation';
      button.title = String((err && err.message) || err);
    });
  }

  function openBankReview(slot) {
    var sheet = sheetShell('spBankReview', 'sp-bankreview',
      String(slot.label || slot.kind || 'Advance preparation'));
    sheet.box.appendChild(make('p', 'sp-bank-summary', bankSlotText(slot)));
    (slot.items || []).forEach(function (item, index) {
      var section = make('section', 'sp-bank-item');
      var name = String(item.kind || slot.kind || 'stock') + ' ' + (index + 1);
      section.appendChild(make('h4', '', name + ' / ' + String(item.state || 'unknown')));
      var lines = make('div', 'sp-bank-lines');
      (item.lines || []).forEach(function (line) {
        var row = make('div', 'sp-bank-line');
        row.dataset.state = String(line.state || '');
        row.appendChild(make('b', '', String(line.who || '')));
        row.appendChild(make('span', '', String(line.text || '(not written)')));
        lines.appendChild(row);
      });
      section.appendChild(lines);
      if (item.round && item.sid) {
        var full = make('button', 'sp-planact', 'Read full script');
        full.type = 'button';
        full.addEventListener('click', function () {
          full.disabled = true;
          api().get('/api/director/script/' + encodeURIComponent(item.sid))
            .then(function (script) {
              lines.replaceChildren();
              (script.turns || []).forEach(function (turn) {
                var row = make('div', 'sp-bank-line');
                row.appendChild(make('b', '', String(turn.who || turn.seat || '')));
                row.appendChild(make('span', '', String(turn.text || '')));
                lines.appendChild(row);
              });
              full.textContent = 'Full script loaded';
            }, function (err) {
              full.disabled = false;
              sheet.say(String((err && err.message) || err), true);
            });
        });
        section.appendChild(full);
      }
      sheet.box.appendChild(section);
    });
    return sheet;
  }

  function paintPlan() {
    var box = el('spPlan');
    if (!box) return;
    if (planIn !== box) { planNodes.clear(); planIn = box; }
    var bankView = bankPlan && Date.now() - bankFetchedAt < 180000
      ? bankPlan : null;
    if (!planHours.length && !bankView) {
      if (planNodes.size) { box.replaceChildren(); planNodes.clear(); }
      paintReadiness();
      return;
    }
    var order = [];
    var wanted = Object.create(null);
    var usedBank = Object.create(null);
    for (var h = 0; h < planHours.length; h += 1) {
      var page = planHours[h] || {};
      var rows = page.entries || [];
      var ahead = [];
      for (var i = 0; i < rows.length; i += 1) {
        /* What has already been said is the screenplay's job; this pane
           is only what is still to come. */
        var st = String(rows[i].state || '');
        if (st === 'aired' || st.indexOf('went by') === 0) continue;
        ahead.push(rows[i]);
      }
      if (!ahead.length) continue;
      var hourKey = 'h:' + h;
      var when = planKeep(hourKey, 'sp-el sp-planhour sp-planjump',
        (h === 0 ? 'STILL TO COME THIS HOUR' : 'THE HOUR AFTER')
        + '  ·  ' + ahead.length
        + (ahead.length === 1 ? ' segment' : ' segments'));
      wanted[hourKey] = 1;
      /* #1294: in `below` the plan sits 60,242 px down a 62,386 px
         scroll - the whole night away from the line being said. The
         heading is the handle back. Attached once, because planKeep
         hands back the SAME node every repaint. */
      if (!when.__jump) {
        when.__jump = 1;
        when.addEventListener('click', function () {
          if (nowLineId) jumpToLine(nowLineId);
        });
      }
      order.push(when);
      for (var k = 0; k < ahead.length; k += 1) {
        var e = ahead[k];
        var bankHit = bankSlotFor(e, bankView, usedBank);
        var bankSlot = bankHit && bankHit.slot;
        if (bankHit) usedBank[bankHit.index] = 1;
        var sc = e.script || {};
        var boundTurns = sc.turns || [];
        var turns = boundTurns.length ? boundTurns : (sc.draft_turns || []);
        var draftOnly = !boundTurns.length && turns.length;
        var mark = String(e.state || '');
        var clock = e.start
          ? new Date(Number(e.start) * 1000).toTimeString().slice(0, 5) : '';
        var segKey = 'p:' + h + ':' + String(e.slot_id || e.ordinal || k);
        var head = planKeep(segKey, 'sp-el sp-planseg'
          + (mark === 'on air' ? ' sp-planlive' : '')
          + (turns.length ? (draftOnly ? ' sp-plandraft' : '')
            : (bankSlot && (bankSlot.items || []).length ? '' : ' sp-planbare'))
          + ((e.orchestration && e.orchestration.status
              && e.orchestration.status !== 'ready') ? ' sp-planshort' : ''),
          (clock ? clock + '  ' : '')
          + String(e.label || e.kind || 'segment').toUpperCase()
          + '   ' + (e.minutes ? e.minutes + ' MIN' : '')
          + (draftOnly ? '   DRAFT READY' : ''));
        head.setAttribute('data-plan', String(e.slot_id || e.ordinal || k));
        head.setAttribute('data-state', mark);
        wanted[segKey] = 1;
        order.push(head);
        var orch = e.orchestration || {};
        if (orch && (orch.say || orch.status)) {
          var have = orch.have || {};
          var target = orch.target || {};
          var needs = Array.isArray(orch.needs) ? orch.needs : [];
          var status = String(orch.status || 'unknown').replace(/[^a-z0-9_-]/gi, '-').toLowerCase();
          var orchKey = segKey + ':orch';
          var orchText = String(orch.say || '')
            + (needs.length ? '  ·  ' + needs.slice(0, 3).join(' · ') : '');
          var orchNode = planKeep(orchKey, 'sp-el sp-planorch sp-planorch-' + status,
            orchText + '  |  ' + planReviewLabel(e));
          orchNode.title = [
            'Written: ' + (orch.stages && orch.stages.written ? 'yes' : 'no'),
            'Reviewed: ' + (orch.stages && orch.stages.reviewed ? 'yes' : 'no'),
            'Recorded: ' + (orch.stages && orch.stages.recorded ? 'yes' : 'no'),
            'Scheduled: ' + (orch.stages && orch.stages.scheduled ? 'yes' : 'no'),
            'Lines: ' + (have.lines || 0) + '/' + (target.lines || 0),
            'Events: ' + (have.events || 0) + '/' + (target.events || 0)
          ].join('\n');
          wanted[orchKey] = 1;
          order.push(orchNode);
        }
        if (bankSlot) {
          var bankKey = segKey + ':bank';
          var bankNode = planKeep(bankKey, 'sp-el sp-planbank', bankSlotText(bankSlot));
          wanted[bankKey] = 1;
          order.push(bankNode);
        }
        var actionKey = segKey + ':actions';
        var actions = planKeep(actionKey, 'sp-plan-actions', '');
        wanted[actionKey] = 1;
        if (orch.preparable) {
          var prepareKey = segKey + ':prepare';
          var prepare = planCommand(prepareKey,
            orch.status === 'ready' ? 'Prepare another' : 'Prepare segment',
            'Ask the orchestrator to prepare this road', function () {
              planPrepare(this);
            });
          prepare.dataset.kind = String(e.kind || '');
          if (prepare.parentNode !== actions) actions.appendChild(prepare);
          wanted[prepareKey] = 1;
        }
        if (turns.length) {
          var reviewKey = segKey + ':review';
          var review = planCommand(reviewKey, 'Review script',
            'Open the prepared lines, revisions and approval for this segment',
            function () {
              itineraryOpen({occurrence: this.dataset.occurrence,
                slot_id: this.dataset.slot});
            });
          review.dataset.occurrence = String(e.occurrence || '');
          review.dataset.slot = String(e.slot_id || '');
          if (review.parentNode !== actions) actions.appendChild(review);
          wanted[reviewKey] = 1;
        }
        if (bankSlot && (bankSlot.items || []).length) {
          var bankReviewKey = segKey + ':bank-review';
          var bankReview = planCommand(bankReviewKey, 'Review banked lines',
            'Read the stock and recording state committed to this slot',
            function () { openBankReview(this.pineBankSlot); });
          bankReview.pineBankSlot = bankSlot;
          if (bankReview.parentNode !== actions) actions.appendChild(bankReview);
          wanted[bankReviewKey] = 1;
        }
        Array.prototype.slice.call(actions.children).forEach(function (button) {
          if (!wanted[button.pineKey]) button.remove();
        });
        if (actions.children.length) order.push(actions);
        if (!turns.length) {
          /* A hole is shown, not hidden: an operator who sees it before
             the slot arrives can still do something about it. */
          var bare = planKeep(segKey + ':why', 'sp-el sp-planwhy',
            bankSlot && (bankSlot.items || []).length
              ? 'No System2 script allocated; banked stock is shown above.'
              : (mark || 'No System2 script allocated to this slot.'));
          wanted[segKey + ':why'] = 1;
          order.push(bare);
          continue;
        }
        for (var t2 = 0; t2 < turns.length; t2 += 1) {
          var turn = turns[t2];
          var cueKey = segKey + ':c' + t2;
          var lineKey = segKey + ':l' + t2;
          order.push(planKeep(cueKey, 'sp-el sp-character sp-plancue',
            String(turn.who || turn.seat || '').toUpperCase()));
          var planLine = planKeep(lineKey, 'sp-el sp-dialogue sp-planline'
            + (draftOnly ? ' sp-plandraftline' : ''), String(turn.text || ''));
          planLine.pineItem = Object.assign({}, turn, {
            id: String(turn.id || turn.line || lineKey),
            line: String(turn.id || turn.line || lineKey),
            text: String(turn.text || ''),
            aired: 'prepared',
            candidate: String(turn.candidate || sc.selected_candidate || sc.candidate || ''),
            segment: String(e.slot_id || e.ordinal || k)
          });
          if (!planLine.__lineOpen) {
            planLine.__lineOpen = 1;
            planLine.setAttribute('role', 'button');
            planLine.setAttribute('tabindex', '0');
            planLine.addEventListener('click', function () {
              openLine(this.pineItem || {}, this);
            });
            planLine.addEventListener('keydown', function (event) {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              event.preventDefault();
              openLine(this.pineItem || {}, this);
            });
          }
          order.push(planLine);
          wanted[cueKey] = 1;
          wanted[lineKey] = 1;
        }
      }
    }
    if (bankView && Array.isArray(bankView.slots)) {
      var unlinked = bankView.slots.filter(function (slot, index) {
        return !usedBank[index];
      });
      if (unlinked.length) {
        var bankHead = planKeep('bank:head', 'sp-el sp-planhour',
          'ADVANCE PREPARATION / BANKED STOCK');
        wanted['bank:head'] = 1;
        order.push(bankHead);
        unlinked.forEach(function (slot, index) {
          var key = 'bank:slot:' + String(slot.commit_id || index);
          var when = Number(slot.in_seconds) || 0;
          var name = planKeep(key, 'sp-el sp-planseg',
            (when ? Math.round(when / 60) + ' MIN AHEAD  ' : 'NOW  ')
            + String(slot.label || slot.kind || 'segment').toUpperCase());
          wanted[key] = 1;
          order.push(name);
          var statusKey = key + ':status';
          order.push(planKeep(statusKey, 'sp-el sp-planbank', bankSlotText(slot)));
          wanted[statusKey] = 1;
          var actKey = key + ':actions';
          var act = planKeep(actKey, 'sp-plan-actions', '');
          wanted[actKey] = 1;
          var prepareKey = key + ':prepare';
          var prepare = planCommand(prepareKey, 'Prepare segment',
            'Ask the orchestrator to prepare this road', function () {
              planPrepare(this);
            });
          prepare.dataset.kind = String(slot.road || slot.kind || '');
          if (prepare.parentNode !== act) act.appendChild(prepare);
          wanted[prepareKey] = 1;
          if ((slot.items || []).length) {
            var reviewKey = key + ':review';
            var review = planCommand(reviewKey, 'Review banked lines',
              'Read the stock and recording state committed to this slot',
              function () { openBankReview(this.pineBankSlot); });
            review.pineBankSlot = slot;
            if (review.parentNode !== act) act.appendChild(review);
            wanted[reviewKey] = 1;
          }
          order.push(act);
        });
      }
    }
    planNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode) held.remove();
      planNodes.delete(key);
    });
    stitchScript(box, order);
    paintReadiness();
  }

  /* #1289: the two layouts differ only in where the plan hangs. */
  function planLayout(way) {
    planWay = (way === 'beside') ? 'beside' : 'below';
    var box = el('spPlan');
    var script = el('spScript');
    if (!box || !script || !script.parentNode) return;
    host.classList.toggle('sp-beside', planWay === 'beside');
    if (planWay === 'below') {
      script.appendChild(box);                 /* one continuous scroll */
    } else {
      script.parentNode.insertBefore(box, script.nextSibling);
    }
  }

  function scriptBlock(item) {
    var type = String(item.type || 'action');
    var node = make('div', 'sp-el sp-' + type);
    node.textContent = String(item.text || '');
    if (item.deleted) node.classList.add('sp-deleted');          /* [#1200] */
    if (item.id) node.dataset.el = String(item.id);
    if (item.line) node.dataset.line = String(item.line);
    if (item.seg) node.dataset.seg = String(item.seg);        /* #1285 */
    if (item.seconds) node.dataset.secs = String(item.seconds);
    if (type === 'scene') {
      /* #1285: the heading is the fold's handle. */
      node.classList.add('sp-fold');
      dressScene(node, item);
      node.setAttribute('role', 'button');
      node.setAttribute('tabindex', '0');
      node.setAttribute('aria-expanded', 'true');
      node.addEventListener('click', function (ev) {
        ev.stopPropagation();        /* not a pane gesture (#1272) */
        /* #1168: "whenever i tap and hold on a segment's header, I want
           a right click menu". The hold has already answered, so this
           click is the synthetic one the platform fires after it -
           swallowing it is what stops a hold also folding the segment
           away underneath its own menu. The same question the caution
           button asks of its own hold. */
        if (node.pineHeld) return;
        segToggle(String((node.pineItem && (node.pineItem.seg || node.pineItem.id))
          || item.seg || item.id || ''));
      });
      node.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
        ev.preventDefault();
        segToggle(String((node.pineItem && (node.pineItem.seg || node.pineItem.id))
          || item.seg || item.id || ''));
      });
      /* #1168: the fifth thing in this file on holdOpen() - half a
         second, eight pixels of travel cancels it, and the desk's
         right-click and the WebView's own long-press are both turned
         into the same answer. Nodes are KEPT and re-dressed across a
         repaint (#1273), so this is attached once per heading and never
         stacked up by a poll. */
      node.setAttribute('aria-haspopup', 'menu');
      node.title = 'Hold this heading (or right-click it): inspect the'
        + ' segment, report it, or examine its system prompt';
      holdOpen(node, function () { segMenuOpen(node); });
    }
    /* A line that has not aired yet is the interesting one - it can still
     * be changed before the room hears it. ONLY 'prepared' is that line;
     * 'published' and 'stream' have both already been heard. */
    if ((item.aired === 'prepared' || item.aired === 'withdrawn')   /* 2026-09-14: refused at hand-over - never aired */) node.classList.add('pending');
    if (item.tinted) node.classList.add('tinted');
    /* #1330: the record that is on the deck RIGHT NOW, not one that
     * finished an hour ago. The two read identically before this, so a
     * script that had just caught up with a track change looked exactly
     * like one that had skipped it - which is how "the script jumped
     * over changing the track" is what a forty second lag looks like
     * from the outside. The server says which; this shows it. */
    if (item.playing) node.classList.add('sp-spinning');
    /* [#1237] the record this line is bound to rides on the node as an
       attribute: the re-dress pass resets textContent and keeps attributes,
       and the stylesheet draws it after the speech. */
    if (item.bound_to) {
      node.dataset.bound = String(item.bound_to);
      node.title = 'Bound to ' + String(item.bound_to)
        + ' - this line airs only while that record is on the deck (#1237)';
    }
    /* #1330: where the SCRIPT put this line. Carried so a reader can
     * follow the running order without re-deriving it, and so the mark
     * can tell a scripted line from one nothing wrote. */
    if (item.block) node.dataset.block = String(item.block);
    if (item.ord !== undefined && item.ord !== null) {
      node.dataset.ord = String(item.ord);
    }
    if (type === 'dialogue' || type === 'action') {
      node.addEventListener('click', function () { openLine(node.pineItem || item, node); });
    }
    return node;
  }

  /* ---------------------------------------------------- the live line */

  /* Where the burst has got to, in its own seconds. Uses the server's clock
   * rather than ours: `server_ms` is stamped in every poll, so the offset
   * between the two machines cancels instead of accumulating. */
  /* #1278: THE PLAYER THAT IS SOUNDING, or null when none is.
   *
   * The DJ voice rides one of a small set of <audio> elements. The one
   * that matters is the one that is actually playing - unpaused, not
   * ended, and past its first frame. */
  /* #1330: THE PANEL'S PLAYHEAD, ACROSS THE WEBVIEW BOUNDARY.
   *
   * soundingPlayer() below scans THIS document. On the desktop chrome
   * that document holds one <audio> (desktopRadioPlayer); djVoiceAudio0/1
   * are created by the panel, which runs inside <webview id="radioFrame">
   * and is a DOM this one cannot reach. So on the chrome the scan
   * returned null every single time - not intermittently - and #1278's
   * read position, #1287's file guard and #1294's named-row preference
   * were all silently dead there, leaving the view on the clock estimate
   * the whole lot was written to replace.
   *
   * webview-preload.js posts the position out; renderer.js stamps it on
   * arrival and hands back null once it is stale. Stale has to mean
   * absent: a frozen mark reads as a working one, which is worse than
   * falling back to the clock and is how this fault survived so long. */
  /* ============================================ THE CUE MAP, PURELY
   *
   * Handed the admission payload and one reading, this says which
   * occurrence and which line the room is in - or says, by name, that it
   * cannot tell. No DOM, no clock, no fetch, so the cases the audit named
   * can be held to it in node without a browser.
   *
   * The eight answers it can give are the synchronization state. Seven of
   * them are not "on air", and the view SHOWS each of them rather than
   * smoothing them into a stationary cursor. */
  var PineScriptCues = (function () {
    var SYNC = {
      READ: 'read',                /* read off the sound and mapped to a cue */
      GAP: 'read-gap',             /* read, inside the file, between cues */
      UNMAPPED: 'read-unmapped',   /* read, but nothing admitted this file */
      OUTSIDE: 'read-outside',     /* read, admitted file, offset off its map */
      ESTIMATED: 'estimated',      /* a clock, not a playhead */
      HELD: 'held',                /* no evidence; the last trustworthy mark */
      PAUSED: 'paused',
      STALL: 'stalled'             /* read, mapped, and no longer moving */
    };
    var TRUSTED = {};
    TRUSTED[SYNC.READ] = true;
    TRUSTED[SYNC.GAP] = true;

    function key(url) {
      var raw = String(url || '').split('?')[0].replace(/\\/g, '/');
      var parts = raw.split('/');
      return parts[parts.length - 1] || '';
    }

    /* [#1189] THE IDENTITY BEHIND A NAME.
       One clip is named four ways on this station and the view compared
       the spelling. A welded round is `/media/<32hex>.wav` (and the same
       key with `?br=` serves mp3 bytes); a sting is `/sfx/<16hex>?t=` -
       the URL keeps the id while the bytes come from the levelled cache,
       whose files are `<16hex>-v2-v<vol>-<mtime>.wav`,
       `<16hex>-<mtime>-src.wav` or `<16hex>-<mark>-<mtime>.<ext>`
       (sfx_levelled_name, _as_wav and sfx_video_levelled in app.py); and a
       feed row carries the same thing under `sfx`, `url`, `media` or
       `clip_media`. This folds every spelling to the one identity the
       station keys on: the 32-hex media key or the 16-hex sample id.
       Anything else answers to its basename. */
    function ident(name) {
      var base = key(name).toLowerCase();
      if (!base) return '';
      var got = /^([0-9a-f]{32})(?:\.[a-z0-9]{1,4})?$/.exec(base);
      if (got) return got[1];
      got = /^([0-9a-f]{16})(?:-[^/]*)?(?:\.[a-z0-9]{1,4})?$/.exec(base);
      if (got) return got[1];
      return base;
    }
    /* NULL IS NOT ZERO, and this is where that matters most.
     *
     * `Number(null)` is 0 and `isFinite(0)` is true, so an absent playhead
     * arrived here as an offset of exactly zero seconds - which lands
     * inside the first cue of whatever file was named and lights its first
     * line with no evidence whatever behind it. A cue whose window the
     * assembler could not supply did the same in reverse: it became the
     * window 0..0 and sat in the sheet as a line that can never be
     * reached. Absent means absent. */
    function num(value) {
      if (value === null || value === undefined || value === '') return null;
      var got = Number(value);
      return isFinite(got) ? got : null;
    }

    /* The station's payload, turned into something that can be searched by
       the one thing the player can tell us: the name of the file it is
       sounding. Occurrences keep their COMMITTED order; nothing here sorts
       by arrival, by air time or by anything that can be rewritten. */
    function read(payload) {
      var out = {ok: false, generation: null, mode: '', enforceOrder: false,
        reader: null, current: null, order: [], byMedia: {}, byIdent: {}, count: 0,   /* [#1189] */
        why: 'the station is not sending an admitted cue map'};
      if (!payload || typeof payload !== 'object') return out;
      out.ok = true;
      out.generation = num(payload.generation);
      out.mode = String(payload.mode || '');
      out.enforceOrder = !!payload.enforce_order;
      out.reader = num(payload.reader_position);
      var rows = payload.occurrences;
      if (!rows || !rows.length) {
        out.why = 'the admitted sequence is empty';
        return out;
      }
      var kept = [];
      for (var i = 0; i < rows.length; i += 1) {
        var row = rows[i];
        if (!row || !row.occurrence_id) continue;
        var audio = row.audio || {};
        var occurrence = {
          occurrence_id: String(row.occurrence_id),
          position: num(row.position),
          state: String(row.state || ''),
          outcome: String(row.outcome || ''),
          lane: String(row.lane || ''),
          producer: String(row.producer || ''),
          origin: String(row.origin || ''),
          media: key(audio.media || audio.path || ''),
          sig: String(audio.sig || ''),
          seconds: num(audio.seconds),
          hash: String(audio.hash || ''),
          dispatched_at: num(row.dispatched_at),
          script_revision: String(row.script_revision || ''),
          assembly_id: String(row.assembly_id || ''),
          cue_map_revision: String(row.cue_map_revision || ''),
          performer_session: String(row.performer_session || ''),
          take_id: String(row.take_id || ''),
          cues: []
        };
        var cues = row.cues || [];
        for (var c = 0; c < cues.length; c += 1) {
          var cue = cues[c];
          if (!cue) continue;
          var from = num(cue.start_s), until = num(cue.end_s);
          if (from === null || until === null) continue;
          occurrence.cues.push({
            line_id: String(cue.line_id || cue.occurrence_id || ''),
            position: num(cue.position),
            ordinal: num(cue.ordinal),
            from: from, until: until,
            speechEnd: num(cue.speech_end_s) === null ? until : num(cue.speech_end_s),
            who: String(cue.who || ''), name: String(cue.name || ''),
            kind: String(cue.kind || ''), text: String(cue.text || '')
          });
        }
        kept.push(occurrence);
      }
      kept.sort(function (a, b) {
        return (a.position === null ? 0 : a.position)
          - (b.position === null ? 0 : b.position);
      });
      out.order = kept;
      out.count = kept.length;
      for (var k = 0; k < kept.length; k += 1) {
        var name = kept[k].media;
        if (!name) continue;
        if (!out.byMedia[name]) out.byMedia[name] = [];
        out.byMedia[name].push(kept[k]);
        var same = ident(name);                                  /* [#1189] */
        if (same && same !== name) {
          if (!out.byIdent[same]) out.byIdent[same] = [];
          out.byIdent[same].push(kept[k]);
        }
      }
      var now = payload.current;
      if (now && now.occurrence_id) {
        out.current = {occurrence_id: String(now.occurrence_id),
          position: num(now.position), media: key(now.media || ''),
          started_at: num(now.started_at), seconds: num(now.seconds)};
      }
      if (!out.why || out.count) out.why = '';
      return out;
    }

    /* WHICH ONE OF SEVERAL PLAYS OF THE SAME FILE.
     *
     * "A reusable sample's content ID is not its playback occurrence ID.
     *  Playing the same sting twice produces two distinct occurrences in
     *  the script."
     *
     * So a file name alone does not settle it. The occurrence the
     * controller says is in flight wins; failing that, the most recently
     * dispatched; failing that, the first still waiting. Picking the last
     * in the list unconditionally is exactly the bug that lit an old
     * burst's line while a new file was playing. */
    function choose(list, current) {
      if (!list || !list.length) return null;
      var i;
      if (current && current.occurrence_id) {
        for (i = 0; i < list.length; i += 1) {
          if (list[i].occurrence_id === current.occurrence_id) return list[i];
        }
      }
      var best = null;
      for (i = 0; i < list.length; i += 1) {
        if (list[i].state !== 'dispatching') continue;
        if (!best || (list[i].position || 0) > (best.position || 0)) best = list[i];
      }
      if (best) return best;
      for (i = list.length - 1; i >= 0; i -= 1) {
        if (list[i].dispatched_at !== null) return list[i];
      }
      return list[0];
    }

    /* [#1189] A CARRIED MARK HAS AN END. #1210's capture read "AIR PAUSED
       - HELD - holding the last read line for 22189s": six hours of a
       stopped station with a line dressed as though it were sounding,
       because `blank()` carried the last trustworthy answer for ever.
       Past ten minutes the carry is dropped - nothing is lit - and the
       answer says when it was last heard instead. */
    var CARRY_MAX_S = 600;
    var carryNow = 0;              /* the reading clock, set by locate() */

    function blank(sync, why, last) {
      var out = {sync: sync, why: why, trustworthy: !!TRUSTED[sync],
        line_id: '', occurrence_id: '', position: null, from: null,
        until: null, speechEnd: null, index: -1, of: 0, media: '',
        origin: '', carried: false};
      if (last && last.line_id) {
        var carriedAt = num(last.at_ms);
        if (carriedAt === null) carriedAt = num(last.at);
        var carriedAge = carriedAt === null ? -1
          : (((carryNow || Date.now()) - carriedAt) / 1000);
        out.carried_age_s = carriedAge >= 0 ? Math.round(carriedAge) : null;
        if (carriedAge > CARRY_MAX_S) {          /* [#1189] history, not a mark */
          out.held_since_ms = carriedAt;
          out.why = why + ' - the last line read was '
            + Math.round(carriedAge / 60) + ' minutes ago; nothing is lit';
          return out;
        }
        /* PRESERVE THE LAST TRUSTWORTHY POSITION - and say it is being
           preserved. A mark with no evidence behind it that looks exactly
           like a mark with evidence behind it is the fault, not the cure. */
        out.line_id = last.line_id;
        out.occurrence_id = last.occurrence_id || '';
        out.position = last.position === undefined ? null : last.position;
        out.media = last.media || '';
        out.origin = last.origin || '';
        out.carried = true;
      }
      return out;
    }

    /* `look`:
         file          what the player says it is sounding
         position_s    its OWN offset into that file, never a wall clock
         source        'bridge' | 'local' | 'estimated' | 'unavailable'
         paused        the air is paused
         stalledMs     how long the read position has been motionless
         stallLimitMs  beyond which motionless is a fault (default 8000)
         last          the last trustworthy answer, to carry */
    function locate(map, look) {
      look = look || {};
      var last = look.last || null;
      carryNow = num(look.now_ms) || Date.now();          /* [#1189] */
      if (look.paused) return blank(SYNC.PAUSED, 'the air is paused', last);
      var source = String(look.source || 'unavailable');
      var at = num(look.position_s);
      if (source === 'unavailable' || at === null || at < 0) {
        return blank(SYNC.HELD, 'no playback evidence is available', last);
      }
      if (source === 'estimated') {
        return blank(SYNC.ESTIMATED,
          'the position is the station clock, not a playhead', last);
      }
      var file = key(look.file);
      if (!file) {
        return blank(SYNC.UNMAPPED, 'the player did not name its file', last);
      }
      if (!map || !map.ok || !map.count) {
        return blank(SYNC.UNMAPPED,
          'no admitted cue map to read ' + file + ' against', last);
      }
      var list = map.byMedia[file] || (map.byIdent && map.byIdent[ident(file)]);   /* [#1189] */
      if (!list || !list.length) {
        return blank(SYNC.UNMAPPED,
          'nothing admitted names ' + file, last);
      }
      var occurrence = choose(list, map.current);
      var got = {sync: SYNC.READ, why: '', trustworthy: true, line_id: '',
        occurrence_id: occurrence.occurrence_id, position: occurrence.position,
        from: null, until: null, speechEnd: null, index: -1,
        of: occurrence.cues.length, media: file, origin: occurrence.origin,
        carried: false, at: at};
      for (var i = 0; i < occurrence.cues.length; i += 1) {
        var cue = occurrence.cues[i];
        if (at >= cue.from && at < cue.until) {
          got.line_id = cue.line_id;
          got.position = cue.position === null ? occurrence.position : cue.position;
          got.from = cue.from; got.until = cue.until;
          got.speechEnd = cue.speechEnd;
          got.index = i;
          var stall = num(look.stalledMs);
          var limit = num(look.stallLimitMs);
          if (limit === null) limit = 8000;
          if (stall !== null && stall > limit) {
            got.sync = SYNC.STALL;
            got.trustworthy = false;
            got.why = 'the playhead has not moved for '
              + Math.round(stall / 1000) + 's';
          }
          return got;
        }
      }
      var span = occurrence.seconds;
      if (span !== null && at > span + 1.5) {
        got.sync = SYNC.OUTSIDE;
        got.trustworthy = false;
        got.why = 'the player is past the end of the cue sheet for ' + file;
        return got;
      }
      got.sync = SYNC.GAP;
      got.why = 'inside ' + file + ', between two committed lines';
      return got;
    }

    /* One short sentence for the operator, per state. */
    function say(got) {
      if (!got) return '';
      if (got.sync === SYNC.READ) return 'in step with the sound';
      if (got.sync === SYNC.GAP) return 'in step - a pause between lines';
      if (got.sync === SYNC.PAUSED) return 'air paused';
      if (got.sync === SYNC.STALL) return 'the sound stopped moving';
      if (got.sync === SYNC.OUTSIDE) return 'the sound is off the cue sheet';
      if (got.sync === SYNC.UNMAPPED) return 'sounding something unadmitted';
      if (got.sync === SYNC.ESTIMATED) return 'estimated - no playhead';
      return 'holding the last known line';
    }

    return {SYNC: SYNC, read: read, locate: locate, choose: choose,
            key: key, ident: ident, say: say};   /* [#1189] */
  }());

  /* ======================================== THE RESOLVER, PURELY  [#1189]
   *
   * "Why did this jump like this?" (#1229, #1228, #1227). Sixteen captures,
   * five findings, one experience: the ON AIR mark leaping to an earlier
   * line, sitting on a line that is not what is sounding, or the page
   * reflowing under the reading eye. Read back from the captures' own
   * event rings, every one of those marks was placed by something that
   * is not evidence of sound:
   *
   *   - the station CLOCK bracketing a window in a different file, with
   *     no file to hold it to (#1248 event 3: 63.4s into an old burst lit
   *     a row 350 elements up, in file 5d109e66 - the estimate road
   *     searched every feed row because nothing was sounding);
   *   - `speaking_now`, the server's four-second notion, which lags a
   *     line behind and never leads (#1205/#1204/#1203: at 14.06s of
   *     6a3fa9b9, past the last window, it named the burst's FIRST line);
   *   - a CARRIED last-known line held for minutes while a different file
   *     sounded (#1197 events 11-16, #1228 event 0, #1234 event 1);
   *   - an `observed:<file>` pseudo-id from the admitted map, which no
   *     node carries, so the mark went dark and markNow chased a fresh
   *     screenplay every three seconds for the whole clip - the document
   *     revisions that churned under the reader (1665, 1680, 1705 inside
   *     one minute of #1205).
   *
   * One law now: ON AIR is placed ONLY by evidence of what is sounding -
   * a read playhead (file + offset) mapped through the cue map, or
   * through a row that names that file - never by the clock, never by
   * speaking_now, never by a carried mark. The clock's guess is still
   * computed and still shown, as a separate dim EXPECTED mark that says
   * what it is.
   *
   * No DOM, no clock, no fetch. Handed the evidence, the tables and the
   * last decision it returns the next decision and the trail that led
   * to it - so the cases above are held to it in node, and the next
   * incident report explains itself. */
  var PineScriptResolver = (function () {
    var LINE_ID = /^[0-9a-f]{32}(?:-punct-\d+)?$/i;
    var NEVER_AIRED = {prepared: 1, withdrawn: 1};
    /* #1210: "AIR PAUSED - HELD - holding the last read line for 22189s".
       Six hours of a stopped station with a line still dressed as though
       it were sounding, because the carry had no end. Ten minutes is the
       end of it: past that the last known line is history, nothing is
       dressed, and the strip says how long ago it was heard. Ten minutes
       is also the same cap `PineScriptCues.locate` applies to its own
       carried answer, so the two roads cannot disagree. */
    var CARRY_MAX_S = 600;         /* a last-known mark older than this is history */
    var BACK_S = 0.3;              /* a playhead step back smaller than this is jitter */
    var ROADS = {
      CUE: 'cue-map',                /* the admitted cue sheet named the line */
      OBSERVED: 'observed-to-page',  /* an observed dispatch, matched to a page row by identity */
      WINDOW: 'feed-window',         /* a row of this file whose window brackets the offset */
      CLIP: 'feed-clip',             /* a row that IS this file - a clip of one line */
      TAIL: 'file-tail',             /* past the last window of the same file: still that clip */
      HELD: 'held-monotone',         /* a backward candidate refused; the last line stands */
      NONE: 'none'
    };

    function num(value) {
      if (value === null || value === undefined || value === '') return null;
      var got = Number(value);
      return isFinite(got) ? got : null;
    }
    function isLineId(id) { return LINE_ID.test(String(id || '')); }

    /* Every name a row answers to, folded to identities. */
    var NAMED = ['clip_media', 'media', 'sfx', 'url', 'clip', 'audio_url', 'clip_url'];
    function identities(row) {
      var out = [];
      if (!row || typeof row !== 'object') return out;
      for (var i = 0; i < NAMED.length; i += 1) {
        var v = row[NAMED[i]];
        if (!v) continue;
        var k = PineScriptCues.ident(v);
        if (k && out.indexOf(k) < 0) out.push(k);
      }
      return out;
    }

    function windowOf(row) {
      var from = num(row.from), until = num(row.until);
      if (from === null) from = num(row.clip_from);
      if (until === null) until = num(row.clip_until);
      return {from: from, until: until};
    }

    /* THE TABLE. Feed rows (the booth ring: clip_media + clip_from, or
       media, sfx, url) and page elements (the screenplay's `line` with
       its clip or url), joined by line id. The feed is fresher for
       `aired` and for windows; the page adds identities the feed has
       rolled out of, and block/ord. */
    function index(feedRows, elements) {
      var byIdent = Object.create(null), byId = Object.create(null), n = 0;
      function entry(id) {
        var got = byId[id];
        if (!got) {
          got = {id: id, from: null, until: null, aired: '', kind: '', who: '',
                 block: null, ord: null, idents: [], windowed: false, source: ''};
          byId[id] = got;
          n += 1;
        }
        return got;
      }
      function name(got, row, source) {
        var ids = identities(row);
        for (var i = 0; i < ids.length; i += 1) {
          if (got.idents.indexOf(ids[i]) < 0) {
            got.idents.push(ids[i]);
            if (!byIdent[ids[i]]) byIdent[ids[i]] = [];
            if (byIdent[ids[i]].indexOf(got) < 0) byIdent[ids[i]].push(got);
          }
        }
        if (!got.source) got.source = source;
      }
      var i, row, got, w;
      for (i = 0; i < (feedRows || []).length; i += 1) {
        row = feedRows[i];
        if (!row || !row.id) continue;
        got = entry(String(row.id));
        w = windowOf(row);
        if (w.from !== null && w.until !== null) { got.from = w.from; got.until = w.until; got.windowed = true; }
        if (row.aired) got.aired = String(row.aired);
        if (row.kind) got.kind = String(row.kind);
        if (row.who) got.who = String(row.who);
        if (num(row.block) !== null) got.block = num(row.block);
        if (num(row.ord) !== null) got.ord = num(row.ord);
        name(got, row, 'feed');
      }
      for (i = 0; i < (elements || []).length; i += 1) {
        row = elements[i];
        if (!row || !row.line) continue;
        got = entry(String(row.line));
        if (!got.aired && row.aired) got.aired = String(row.aired);
        if (got.block === null && num(row.block) !== null) got.block = num(row.block);
        if (got.ord === null && num(row.ord) !== null) got.ord = num(row.ord);
        if (!got.kind && row.type) got.kind = String(row.type);
        name(got, row, 'page');
      }
      return {byIdent: byIdent, byId: byId, count: n};
    }

    /* Of the rows that name this file: the windowed one bracketing `at`,
       else the last windowless one (a clip of one line). Two windowed rows
       bracketing the same offset is the feed's own re-air twin; the later
       `from` is the freshest. */
    function pick(list, at) {
      var hit = null, lone = null;
      for (var i = 0; i < (list || []).length; i += 1) {
        var e = list[i];
        if (e.windowed) {
          if (at !== null && at >= e.from && at < e.until && (!hit || e.from >= hit.from)) hit = e;
        } else {
          lone = e;
        }
      }
      return hit || lone;
    }

    function carry(d, state, now, otherFile) {
      var lg = state.lastGood;
      if (!lg || !lg.line_id) return;
      var age = (now - (num(lg.at_ms) === null ? (num(lg.at) || 0) : num(lg.at_ms))) / 1000;
      if (!(age >= 0 && age <= CARRY_MAX_S)) return;
      /* A different file is sounding and nothing names it: the last line
         is not "what is sounding", so it is not shown as though it were. */
      if (otherFile && lg.key && lg.key !== d.key) return;
      d.carried_id = String(lg.line_id);
      d.carried_age_s = Math.round(age);
    }

    function refuse(d, road, id, why) {
      if (d.refused.length < 6) d.refused.push({road: road, id: String(id || ''), why: why});
    }

    /* look:   {source, file, position_s, paused, stalledMs, stallLimitMs,
                now_ms, expected: {id, via} | null}
       tables: {map: PineScriptCues.read(...), index: index(...)}
       state:  {airLast, lastGood}                                          */
    function resolve(look, tables, state) {
      look = look || {}; tables = tables || {}; state = state || {};
      var S = PineScriptCues.SYNC;
      var now = num(look.now_ms);
      if (now === null) now = Date.now();
      var d = {at_ms: now, source: String(look.source || 'unavailable'),
        file: PineScriptCues.key(look.file), key: PineScriptCues.ident(look.file),
        t: num(look.position_s), mark: 'none', line_id: '', road: ROADS.NONE,
        why: '', sync: S.HELD, trustworthy: false, occurrence_id: '', position: null,
        from: null, until: null, index: -1, of: 0, block: null, ord: null,
        observed: '', expected_id: String((look.expected && look.expected.id) || ''),
        expected_via: String((look.expected && look.expected.via) || ''),
        carried_id: '', carried_age_s: null, refused: []};
      var last = state.airLast || null;
      var read = (d.source === 'bridge' || d.source === 'local')
        && d.t !== null && d.t >= 0 && !!d.key;
      if (look.paused) {
        d.sync = S.PAUSED; d.why = 'the air is paused';
        carry(d, state, now, false);
        return d;
      }
      if (!read) {
        d.sync = d.source === 'estimated' ? S.ESTIMATED : S.HELD;
        d.why = d.source === 'estimated'
          ? 'no playhead - the station clock only guesses, so nothing is marked on air'
          : 'no playback evidence is available';
        carry(d, state, now, false);
        return d;
      }
      /* Road 1: the admitted cue sheet, when the station committed one
         for this file. */
      var map = tables.map, got = null, candidate = null;
      var idx = tables.index || {byIdent: {}, byId: {}};
      if (map && map.ok && map.count) {
        got = PineScriptCues.locate(map, {file: d.file, position_s: d.t, source: d.source,
          stalledMs: look.stalledMs, stallLimitMs: look.stallLimitMs});
        d.sync = got.sync; d.why = got.why; d.occurrence_id = got.occurrence_id;
        d.position = got.position; d.of = got.of; d.index = got.index;
        if (got.line_id && isLineId(got.line_id)) {
          candidate = {id: got.line_id, from: got.from, until: got.until, road: ROADS.CUE};
        } else if (got.line_id) {
          d.observed = String(got.line_id);        /* observed:<file> - a clip, not a line */
        }
      }
      /* Roads 2 and 3: a row that names this file - the cue map's observed
         clip resolved to the page, or straight from the feed and the page. */
      if (!candidate) {
        var hit = pick(idx.byIdent ? idx.byIdent[d.key] : null, d.t);
        if (hit) {
          candidate = {id: hit.id, from: hit.from, until: hit.until,
            road: d.observed ? ROADS.OBSERVED : (hit.windowed ? ROADS.WINDOW : ROADS.CLIP)};
        }
      }
      var entry = candidate && idx.byId ? idx.byId[candidate.id] : null;
      /* (b) A line the station never put out cannot be sounding. */
      if (candidate && entry && NEVER_AIRED[entry.aired]) {
        refuse(d, candidate.road, candidate.id, 'aired=' + entry.aired + ' - never put out');
        candidate = null;
      }
      /* (d) While the same file plays forward, the line cannot move to an
         earlier window of it. A step back in the playhead itself - a seek,
         the same sting played twice - resets the guard. */
      var sameFile = !!(last && last.key === d.key && last.t !== null && d.t >= last.t - BACK_S);
      var held = false;
      if (candidate && sameFile && candidate.id !== last.line_id) {
        var earlier = (candidate.from !== null && last.from !== null && candidate.from < last.from - 0.05)
          || (entry && last.block !== null && entry.block === last.block
              && entry.ord !== null && last.ord !== null && entry.ord < last.ord);
        if (earlier) {
          refuse(d, candidate.road, candidate.id, 'earlier in the same file than '
            + String(last.line_id).slice(0, 8) + ' (from ' + candidate.from + ' < ' + last.from + ')');
          candidate = null; held = true;
        }
      }
      /* Road 4: past every window of the file that is still sounding - the
         tail of the clip (a hang-up, room tone, an inserted pause). The
         audit's stationary cursor across a declared gap. */
      if (!candidate && sameFile) {
        candidate = {id: last.line_id, from: last.from, until: last.until,
          road: held ? ROADS.HELD : ROADS.TAIL};
        entry = (idx.byId && idx.byId[candidate.id]) || entry;
      }
      if (candidate) {
        d.mark = 'air'; d.line_id = String(candidate.id); d.road = candidate.road;
        d.from = candidate.from; d.until = candidate.until;
        if (entry) { d.block = entry.block; d.ord = entry.ord; }
        if (candidate.road !== ROADS.CUE) {
          if (got && got.sync === S.STALL) d.sync = S.STALL;
          else if (candidate.road === ROADS.TAIL || candidate.road === ROADS.HELD) d.sync = S.GAP;
          else d.sync = S.READ;
          d.why = candidate.road === ROADS.OBSERVED
              ? 'read off the sound; the station observed this clip and the page names it'
            : candidate.road === ROADS.WINDOW
              ? 'read off the sound; a feed row of ' + d.file + ' brackets ' + d.t.toFixed(1) + 's'
            : candidate.road === ROADS.CLIP
              ? 'read off the sound; this row is the whole of ' + d.file
            : candidate.road === ROADS.TAIL
              ? 'the tail of ' + d.file + ' - past its last line, still sounding'
            : 'a backward candidate was refused; the last line of ' + d.file + ' stands';
        }
        d.trustworthy = d.sync === S.READ || d.sync === S.GAP;
        return d;
      }
      /* Evidence, and nothing on the page answers to it. Said plainly. */
      if (d.sync === S.READ || d.sync === S.HELD || d.sync === S.ESTIMATED) d.sync = S.UNMAPPED;
      d.why = d.observed
        ? 'sounding ' + d.file + ' - an observed dispatch nothing on the page names'
        : (got && got.why && d.sync !== S.UNMAPPED)
          ? got.why
          : 'sounding ' + d.file + ' - nothing on the page names it';
      carry(d, state, now, true);
      return d;
    }

    /* A short sentence for the operator, per decision. */
    function say(d) {
      if (!d) return '';
      var S = PineScriptCues.SYNC;
      if (d.mark === 'air') {
        if (d.sync === S.STALL) return 'the sound stopped moving';
        return d.road === ROADS.CUE ? 'in step with the sound' : 'read off the sound';
      }
      if (d.sync === S.PAUSED) return 'air paused';
      if (d.source === 'estimated') return 'expected - no playhead';
      if (d.sync === S.UNMAPPED) return 'sounding something the page does not name';
      return 'nothing sounding';
    }

    return {resolve: resolve, index: index, identities: identities, pick: pick,
            isLineId: isLineId, ROADS: ROADS, CARRY_MAX_S: CARRY_MAX_S, say: say};
  }());

  function bridgeHead() {
    try { return (root.pinePlayhead && root.pinePlayhead()) || null; }
    catch (e) { return null; }
  }

  /* True when the position is READ off the sound, false when it is
   * estimated. The searches below are only trustworthy in the first
   * case, and they had no way to ask. */
  function headIsRead() {
    return !!(bridgeHead() || soundingPlayer());
  }

  function soundingPlayer() {
    var all = document.querySelectorAll('audio');
    for (var i = 0; i < all.length; i += 1) {
      var a = all[i];
      if (!a || a.paused || a.ended) continue;
      if (!/djVoice/i.test(String(a.id || ''))) continue;
      if (!(Number(a.currentTime) > 0)) continue;
      return a;
    }
    return null;
  }

  /* Where the burst has got to, in its own seconds.
   *
   * #1278: READ, NOT ESTIMATED. This used to be
   * `(Date.now() + skewMs)/1000 - liveStream.at`, and `skewMs` is
   * re-read from `server_ms` on every poll, so it carried the whole
   * delivery latency and all its jitter. Measured against the audio
   * over 308 samples: behind the sound in 81.3% of them, off by more
   * than three seconds in 58.5%, median -2.99s; skewMs spread 16.7s and
   * moved a median of 1.79s between polls; the clock stalled in 61.3%
   * of intervals and then lurched. Against six-second lines that is
   * precisely a mark that skips forward and snaps back - 29.8% of moves
   * were skips and 20.5% were backward, 26 of those 31 with the
   * document completely unchanged.
   *
   * The audio element's currentTime is the SAME coordinate as the rows'
   * from/until - both are offsets into the same welded file - so the
   * position does not have to be estimated. Verified: a burst's maximum
   * `until` 86.86s against the player's own duration 87.76s.
   *
   * The clock remains for the one case with nothing to read: no player
   * sounding. */
  function streamAt() {
    var head = bridgeHead();                              /* #1330 */
    if (head) return Number(head.t) || 0;
    var player = soundingPlayer();
    if (player) return Number(player.currentTime) || 0;
    if (!liveStream || !liveStream.at) return -1;
    return ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
  }

  /* The row the room is hearing. stream_now first - it is exact to the
   * quarter second - and speaking_now only as a fallback, since it is
   * refreshed every four seconds and a four second lag on a four second
   * line points at the wrong one. */
  /* #1287: the basename of the file the player is actually sounding,
     so a row can be asked whether it belongs to it. `from`/`until` are
     offsets into a row's OWN file, and matching them without checking
     the file is how a row 99 seconds away wins - 23 of the 24
     wrong-line samples were exactly that. */
  function soundingFile() {
    var head = bridgeHead();                              /* #1330 */
    if (head) return String(head.file || '');
    var a = soundingPlayer();
    if (!a) return '';
    var src = String(a.currentSrc || a.src || '').split('?')[0];
    return src.split('/').pop() || '';
  }

  /* [#1189] EVERY NAME A ROW ANSWERS TO.
     A board sting's ring row has no `media` and no `clip_media` at all -
     it is `sfx: <16hex>` and `url: /sfx/<16hex>?t=<sig>` (app.py
     76557-76575) - so this returned '' and the row could never be held
     to the file that was sounding. That is #1188 (two stings played
     while the mark sat 9 elements above them for 20s), #1197, #1228,
     #1234 and the opening of #1203/#1204: "the script jumped" with the
     script standing perfectly still. An ad is the same shape under
     `/ads-audio/<name>.mp3`. The basename of `url` with its query
     stripped, and the raw `sfx` key, are the same clip under two more
     spellings; `soundingFile()` already reduces the player's own source
     to exactly that basename, so the two sides now meet. */
  function rowFile(row) {
    var named = String(row.clip_media || row.media || '');
    if (named) return named;
    var url = String(row.url || row.clip || '').split('?')[0].replace(/\\/g, '/');
    var base = url.split('/').pop();
    if (base) return base;
    return String(row.sfx || '');
  }

  /* #1294: a row's window under EITHER name.
   *
   * The burst table calls them from/until; the feed calls them
   * clip_from/clip_until, and 168 of 171 feed rows carry only the
   * second pair. within() read only the first, so on the feed every
   * multi-row file collapsed into the lone-row branch and the last row
   * of the file won the whole file. */
  function rowFrom(row) {
    var v = Number(row.from);
    return isFinite(v) ? v : Number(row.clip_from);
  }

  function rowUntil(row) {
    var v = Number(row.until);
    return isFinite(v) ? v : Number(row.clip_until);
  }

  /* [#1189] THE ONE ROAD TO THE MARK. Evidence in, decision out. The
     roads that used to place the mark - the clock inside stream_now, the
     feed searched without a file, speaking_now - live on as estimateRow()
     below, and feed the EXPECTED mark and nothing else. */
  var lastDecision = null;
  var airLast = null;                 /* the last ON AIR decision, for the monotone guard */
  var resolverRing = [];              /* bounded: what the resolver decided, and why */
  var RESOLVER_RING_MAX = 120;
  var feedIndexHeld = null, feedIndexAt = 0, feedIndexRows = -1, feedIndexEls = -1;

  function feedIndex() {
    var now = Date.now();
    var fed = [];
    try { fed = root.PineStationFeed.rows() || []; } catch (e) { fed = []; }
    /* rows() is rebuilt every tick; the table is rebuilt once a second, or
       sooner when either source changes size. */
    if (feedIndexHeld && now - feedIndexAt < 1000
        && fed.length === feedIndexRows && elements.length === feedIndexEls) return feedIndexHeld;
    feedIndexHeld = PineScriptResolver.index(fed, elements);
    feedIndexAt = now; feedIndexRows = fed.length; feedIndexEls = elements.length;
    return feedIndexHeld;
  }

  /* What the player says, and only what the player says. The clock is
     reported as `estimated` so the resolver can refuse it by name. */
  function evidence() {
    var head = bridgeHead();
    var player = head ? null : soundingPlayer();
    var source = head ? 'bridge' : (player ? 'local' : 'unavailable');
    var at = null, file = '';
    if (head) { at = Number(head.t); file = String(head.file || ''); }
    else if (player) {
      at = Number(player.currentTime);
      file = String(player.currentSrc || player.src || '');
    } else if (liveStream && liveStream.at) {
      source = 'estimated';
      at = ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
    }
    var moved = 0;
    if (source === 'bridge' || source === 'local') {
      var now = Date.now();
      if (headWas < 0 || Math.abs(Number(at) - headWas) > 0.05) {
        headWas = Number(at); headMovedAt = now;
      }
      moved = headMovedAt ? now - headMovedAt : 0;
    } else { headWas = -1; headMovedAt = 0; }
    return {source: source, file: file, position_s: at, stalledMs: moved};
  }

  function activeRow() {
    var look = evidence();
    var expected = null;
    try { expected = estimateRow(); } catch (e) { expected = null; }
    look.paused = stationPaused;
    look.stallLimitMs = STALL_MS;
    look.now_ms = Date.now();
    look.expected = (expected && expected.id)
      ? {id: String(expected.id), via: headIsRead() ? 'feed-tables' : 'station-clock'}
      : null;
    var d = PineScriptResolver.resolve(look, {map: admitMap, index: feedIndex()},
                                       {airLast: airLast, lastGood: lastGood});
    /* The linear playout controller is the station's final word. Local media
       evidence normally arrives faster, but when the two disagree a fresh
       line id from /api/playout names the occurrence that is actually
       sounding and must drive both the strip and the highlight. */
    var verdict = playoutNow;
    if (playoutEvidence(verdict, look, stationPaused, Date.now())
        && Date.now() - Number(verdict.at_ms || 0) <= PLAYOUT_MS * 3) {
      d = Object.assign({}, d, {
        mark: 'air',
        line_id: String(verdict.line_id),
        occurrence_id: String(verdict.occurrence_id || d.occurrence_id || ''),
        block: verdict.block,
        ord: verdict.ord,
        t: verdict.offset_s === null ? d.t : verdict.offset_s,
        from: verdict.line_from === null ? d.from : verdict.line_from,
        until: verdict.line_until === null ? d.until : verdict.line_until,
        source: 'playout',
        road: 'playout',
        sync: 'locked',
        trustworthy: true,
        at_ms: Date.now(),
        why: 'the station playout controller names this exact sounding line',
        refused: d.refused || []
      });
    }
    if (d.mark === 'air') {
      airLast = {line_id: d.line_id, key: d.key, t: d.t, from: d.from, until: d.until,
                 block: d.block, ord: d.ord, at_ms: d.at_ms};
    }
    if (d.trustworthy && d.line_id) {
      lastGood = {line_id: d.line_id, occurrence_id: d.occurrence_id, position: d.position,
                  media: d.file, key: d.key, origin: '', at: d.at_ms, at_ms: d.at_ms};
    }
    if (syncState !== d.sync) { syncState = d.sync; syncSince = d.at_ms; }
    syncWhy = d.why || PineScriptCues.say({sync: d.sync});
    var seen = resolverRing[resolverRing.length - 1];
    if (!seen || seen.mark !== d.mark || seen.line_id !== d.line_id || seen.road !== d.road
        || seen.sync !== d.sync || seen.key !== d.key || seen.refused !== d.refused.length
        || seen.expected_id !== d.expected_id || seen.carried_id !== d.carried_id) {
      resolverRing.push({at_ms: d.at_ms, mark: d.mark, line_id: d.line_id, road: d.road,
        sync: d.sync, source: d.source, key: d.key,
        t: d.t === null ? null : Math.round(d.t * 1000) / 1000,
        why: String(d.why || '').slice(0, 160), refused: d.refused.length,
        refused_why: d.refused.length ? String(d.refused[0].why || '').slice(0, 120) : '',
        expected_id: d.expected_id, carried_id: d.carried_id,
        occurrence_id: d.occurrence_id});
      if (resolverRing.length > RESOLVER_RING_MAX) resolverRing.shift();
    }
    lastDecision = d;
    if (d.mark !== 'air') return null;
    return {id: d.line_id, from: Number(d.from || 0), until: Number(d.until || 0),
      at: Number(d.t || 0), index: d.index, of: d.of, occurrence_id: d.occurrence_id,
      position: d.position, sync: d.sync, carried: false,
      admitted: d.road === PineScriptResolver.ROADS.CUE, road: d.road,
      text: d.road === 'playout' ? String(verdict.text || '') : '',
      speaker: d.road === 'playout' ? String(verdict.speaker || '') : ''};
  }

  /* The decision, compact, for the incident capture. */
  function resolverSnapshot() {
    var d = lastDecision;
    var decision = null;
    if (d) {
      decision = {at_ms: d.at_ms, source: d.source, file: d.file, key: d.key, t: d.t,
        mark: d.mark, line_id: d.line_id, road: d.road, sync: d.sync, why: String(d.why || '').slice(0, 200),
        occurrence_id: d.occurrence_id, position: d.position, from: d.from, until: d.until,
        block: d.block, ord: d.ord, observed: d.observed, expected_id: d.expected_id,
        expected_via: d.expected_via, carried_id: d.carried_id, carried_age_s: d.carried_age_s,
        refused: d.refused.slice(0, 6)};
    }
    return {decision: decision, ring: resolverRing.slice(-40)};
  }

  /* ---------------------------------------------- THE MARKS  [#1189]
     Three marks, one node each, placed idempotently and re-asserted on the
     keyed node after every repaint: .sp-now is ON AIR (evidence only),
     .sp-expect is the clock's guess when there is no evidence, .sp-last
     is the last line heard while nothing sounds. */
  var dressed = Object.create(null);

  function lineNode(id) {
    if (!id) return null;
    id = String(id);
    var cached = lineNodes.get(id);
    if (cached && cached.isConnected && cached.dataset.line === id) return cached;
    return document.querySelector('.sp-el[data-line="' + id + '"]');
  }

  function revealLine(id, onAir) {
    var node = lineNode(id);
    if (node) return node;
    var held = lineNodes.get(String(id || ''));
    if (!held || !held.dataset.seg || !scriptOrder.length) return null;
    var seg = String(held.dataset.seg);
    if (onAir) {
      if (liveSeg !== seg) segFollow(seg);
      else { folded[seg] = false; segApply(false); }
    } else {
      folded[seg] = false;
      byHand[seg] = true;
      segApply(false);
      foldSave();
    }
    return lineNode(id);
  }

  /* The CHARACTER cue above a line, for the status sentence. */
  function lineWho(id) {
    var node = lineNode(id);
    if (!node) return '';
    var prev = node.previousElementSibling;
    if (prev && prev.classList && prev.classList.contains('sp-character')) {
      return String(prev.textContent || '') + ' ';
    }
    return '';
  }

  function dress(cls, id) {
    id = String(id || '');
    if (dressed[cls] === id) {
      var same = id ? lineNode(id) : null;
      if (same && !same.classList.contains(cls)) same.classList.add(cls);
      return;
    }
    var lit = document.querySelectorAll('.sp-el.' + cls);
    for (var i = 0; i < lit.length; i += 1) lit[i].classList.remove(cls);
    dressed[cls] = id;
    var node = id ? lineNode(id) : null;
    if (node) node.classList.add(cls);
  }

  function sayingFallbackMark(row, shown) {
    return null;
  }

  function placeMarks(d, fallback) {
    d = d || lastDecision || {};
    var air = d.mark === 'air' ? String(d.line_id || '') : '';
    markNow(air);
    var liveNode = lineNode(air);
    if (liveNode) liveNode.classList.remove('sp-feed-now');
    dress('sp-expect', (!air && d.expected_id && d.expected_id !== d.carried_id) ? d.expected_id : '');
    dress('sp-last', (!air && d.carried_id) ? d.carried_id : '');
  }

  /* (c) THE LIT LINE STAYS WHERE THE EYE IS. A fold, a repaint or an
     insert above can move the lit node out of the pane with no line
     change to re-follow on (#1248: scroll ran 1,772px past the line while
     follow was on). Rate-limited; never while a move of ours is in flight;
     never against a hand scroll, which stands follow down first. */
  var keptAt = 0;
  function keepLitInView(reason) {
    if (!follow) return false;
    var box = el('spScript');
    if (!box) return false;
    var now = Date.now();
    if (now < selfScrollUntil) return false;
    if (reason !== 'paint' && now - keptAt < 900) return false;
    var node = lineNode(nowLineId);
    if (!node || node.hidden) return false;
    keptAt = now;
    var pane = box.getBoundingClientRect(), seat = node.getBoundingClientRect();
    if (!(seat.height > 0)) return false;
    var out = seat.bottom <= pane.top || seat.top >= pane.bottom;
    if (!out) return false;
    return moveScript('follow:' + (reason || 'drift'), function (pane) {
      seatLineNearest(pane, node);
    });
  }

  /* The reader's place across a fold: measured on the lit node when it is
     on screen (that is what they are reading), else on the first visible
     element, and restored by the drift once the fold has committed. */
  var foldHold = null;
  var foldGuardSerial = 0;
  var foldGuardTimer = 0;
  function foldGuardStart() {
    foldGuardSerial += 1;
    var serial = foldGuardSerial;
    var box = el('spScript');
    if (!box) { foldHold = null; return serial; }
    var node = lineNode(nowLineId);
    var pane = box.getBoundingClientRect();
    if (node && !node.hidden) {
      var seat = node.getBoundingClientRect();
      if (!(seat.height > 0 && seat.bottom > pane.top && seat.top < pane.bottom)) node = null;
    } else node = null;
    if (!node) {
      var anchor = scriptAnchor(box);
      foldHold = anchor && anchor.node
        ? {node: anchor.node, was: anchor.was, line: String(nowLineId || ''), serial: serial}
        : null;
      return serial;
    }
    foldHold = {node: node, was: node.getBoundingClientRect().top,
      line: String(nowLineId || ''), serial: serial};
    return serial;
  }
  function foldGuardEnd(reason, serial) {
    var hold = foldHold;
    if (serial !== foldGuardSerial || !hold || hold.serial !== serial) return;
    foldHold = null;
    var box = el('spScript');
    /* A delayed fold callback belongs to the line that opened it. The
       next line's follow has already seated the reader correctly; applying
       the old anchor to the new line is the measured 1,300px snap. */
    if (hold.line !== String(nowLineId || '')) return;
    if (!hold || !box || !hold.node || hold.node.parentNode !== box || hold.node.hidden) return;
    var drift = hold.node.getBoundingClientRect().top - hold.was;
    if (Math.abs(drift) > 0.5) {
      moveScript('fold:' + (reason || 'settle'), function (pane) {
        pane.scrollTop = Math.max(0, pane.scrollTop + drift);
      });
    }
  }

  /* ---------------------------------------- THE STATION'S VERDICT  [#1189]
     GET /api/playout (the linear playout controller) says which occurrence
     is sounding, by its own reading. Feature-tested: a station without it
     answers 404 through the bridge as a rejection, and the strip simply
     does not show a verdict. Asked every four seconds when present, once
     every ten minutes when absent. */
  var playoutNow = null;
  var playoutState = 'unknown';
  var playoutAt = 0;
  var playoutBusy = false;
  var PLAYOUT_MS = 800;
  var PLAYOUT_RETRY_MS = 600000;

  function playoutRead(got) {
    if (!got || typeof got !== 'object') return null;
    var s = got.sounding || got.current || got.now || {};
    var verdict = String(got.verdict || got.state || '');
    if (!verdict && !s.occurrence_id) return null;
    var off = s.offset_s;
    if (off === undefined) off = s.offset;
    if (off === undefined) off = s.position_s;
    return {verdict: verdict.slice(0, 80),
      occurrence_id: String(s.occurrence_id || s.occurrence || s.id || ''),
      line_id: String(s.line_id || s.line || ''),
      block: (s.block === undefined || s.block === null) ? null : Number(s.block),
      ord: (s.ord === undefined || s.ord === null) ? null : Number(s.ord),
      file: PineScriptCues.key(s.file || s.media || ''),
      offset_s: (off === undefined || off === null || !isFinite(Number(off))) ? null : Number(off),
      line_from: isFinite(Number(s.line_from)) && s.line_from != null ? Number(s.line_from) : null,
      line_until: isFinite(Number(s.line_until)) && s.line_until != null ? Number(s.line_until) : null,
      speaker: String(s.speaker || ''), text: String(s.text || ''),
      position_basis: String(s.position_basis || ''),
      last_heard_at: Number(s.last_heard_at) || 0,
      next: got.next && typeof got.next === 'object'
        ? {occurrence_id: String(got.next.occurrence_id || ''), line_id: String(got.next.line_id || ''),
           block: got.next.block === undefined ? null : got.next.block,
           ord: got.next.ord === undefined ? null : got.next.ord}
        : null,
      at_ms: Date.now()};
  }

  function playoutEvidence(receipt, read, paused, nowMs) {
    if (!receipt || !receipt.line_id || paused
        || !read || (read.source !== 'local' && read.source !== 'bridge')
        || receipt.position_basis !== 'listener'
        || !isFinite(Number(receipt.last_heard_at))
        || Number(receipt.last_heard_at) <= 0
        || receipt.offset_s === null || !isFinite(Number(receipt.offset_s))
        || read.position_s === null || !isFinite(Number(read.position_s))
        || Number(read.stalledMs || 0) >= STALL_MS) return false;
    var age = nowMs / 1000 - Number(receipt.last_heard_at);
    if (age < -3 || age > 3) return false;
    var from = receipt.line_from, until = receipt.line_until;
    if (from !== null && until !== null && (
      Number(receipt.offset_s) < Number(from) - 0.25
      || Number(receipt.offset_s) >= Number(until) + 0.25)) return false;
    if (!read.file || !receipt.file
        || PineScriptCues.key(read.file) !== receipt.file) return false;
    if (from !== null && until !== null
        && (Number(read.position_s) < Number(from)
          || Number(read.position_s) >= Number(until))) return false;
    return true;
  }

  function playoutPoll() {
    var now = Date.now();
    if (playoutBusy) return;
    if (playoutState === 'absent' && now - playoutAt < PLAYOUT_RETRY_MS) return;
    if (playoutState === 'present' && now - playoutAt < PLAYOUT_MS) return;
    if (playoutState === 'unknown' && now - playoutAt < PLAYOUT_MS) return;
    var bridge = api();
    if (!bridge || typeof bridge.get !== 'function') return;
    playoutBusy = true;
    playoutAt = now;
    var ask;
    try { ask = Promise.resolve(bridge.get('/api/playout?limit=1&lean=1')); }
    catch (err) { playoutBusy = false; playoutState = 'absent'; playoutNow = null; return; }
    ask.then(function (got) {
      playoutBusy = false;
      var read = playoutRead(got);
      if (!read) { playoutState = 'absent'; playoutNow = null; return; }
      playoutState = 'present';
      playoutNow = read;
    }, function () {
      playoutBusy = false;
      playoutState = 'absent';
      playoutNow = null;
    });
  }

  /* Does the station's verdict name what this view marked? null = cannot
     tell (no verdict, or the verdict carries no identity). */
  function playoutAgrees() {
    var p = playoutNow, d = lastDecision;
    if (!p || !d) return null;
    if (Date.now() - p.at_ms > PLAYOUT_MS * 3) return null;
    if (d.mark !== 'air') return null;
    if (p.line_id) return p.line_id === d.line_id;
    if (p.occurrence_id && d.occurrence_id) return p.occurrence_id === d.occurrence_id;
    if (p.block !== null && d.block !== null) return p.block === d.block && (p.ord === null || d.ord === null || p.ord === d.ord);
    return null;
  }

  function playoutWord() {
    var p = playoutNow;
    if (!p || Date.now() - p.at_ms > PLAYOUT_MS * 3) return '';
    var words = p.verdict ? 'station: ' + p.verdict : 'station: sounding';
    if (p.block !== null) words += ' ' + p.block + (p.ord !== null ? '.' + p.ord : '');
    var agrees = playoutAgrees();
    if (agrees === false) words += ' (the view disagrees)';
    return words;
  }

  function paintPlayout(strip) {
    if (!strip) return;
    var node = strip.querySelector('.sp-sync-playout');
    var words = playoutWord();
    if (!node) {
      if (!words) return;
      node = make('u', 'sp-sync-playout', '');
      strip.insertBefore(node, strip.lastChild);
    }
    var agrees = playoutAgrees();
    node.classList.toggle('sp-disagree', agrees === false);
    if (node.__text !== words) { node.__text = words; node.textContent = words; }
  }

  /* [#1189] THE EXPECTED LINE - the roads that used to place the mark.
     The clock inside stream_now, the feed searched with no file to hold a
     row to, and speaking_now: each was measured placing the mark wrongly
     (see PineScriptResolver above), so none of them touches ON AIR now.
     They still answer "where does the station think it is", and that is
     drawn as EXPECTED, dim and labelled, when there is no evidence. */
  function estimateRow() {                                   /* [#1189] */
    /* #1336 / the sequential-playout audit: the ADMITTED map first. Every
       road below this line reconstructs a position from something that can
       be rewritten - estimates, feed rows, a four-second poll. The cue
       sheet the controller committed cannot be. */
    /* [#1189] the admitted map is read by the resolver; this road only estimates. */
    var t = streamAt();    var rows = (liveStream && liveStream.rows) || [];
    var file = soundingFile();
    /* #1330: A BURST THAT HAS RUN OUT IS NOT A TABLE TO SEARCH.
     *
     * With an estimated position there is no filename to hold a row to,
     * so #1287's guard cannot fire and a finished burst's windows still
     * bracket the estimate - lighting a row that stopped sounding some
     * time ago and holding it lit. #1294 measured that shape: 12 of 19
     * wrong samples were more than two seconds in.
     *
     * The station's own reader already refuses this - it accepts an
     * offset only inside [0, length + 4] before falling back to
     * speaking_now - and the view should refuse it on the same terms.
     * Where the position is READ this cannot arise, because the file
     * guard settles it; this is only for where we are guessing. */
    if (!headIsRead() && liveStream && liveStream.at) {
      var span = Number(liveStream.length || 0) + 4;
      if (!(t >= 0 && t <= span)) {
        return (speakingNow && speakingNow.id)
          ? {id: String(speakingNow.id), from: 0, until: 0, at: t,
             index: -1, of: rows.length}
          : null;
      }
    }
    function within(list, of) {
      var lone = null, loneAt = -1;
      for (var i = 0; i < list.length; i += 1) {
        var row = list[i];
        var mine = rowFile(row);
        /* #1287: only rows of the file that is sounding. */
        if (file && mine && mine !== file) continue;
        var from = rowFrom(row), until = rowUntil(row);
        if (!isFinite(from) || !isFinite(until)) {
          /* #1287: A ROW THAT IS THE WHOLE FILE HAS NO WINDOW.
           * Measured: 0 of 25 `interject` rows carry from/until - they
           * are a clip of one line, so there is nothing to offset
           * into - and interject was lit correctly 0 of 37 times. My
           * #1278 note claimed the wider search would catch them; it
           * could not, because the field its loop needs does not
           * exist on them. If the sounding file IS this row's file,
           * this row is the line. */
          if (file && mine === file) { lone = row; loneAt = i; }
          continue;
        }
        if (t >= from && t < until) {
          return {id: String(row.id || ''), from: from, until: until,
            at: t, index: i, of: of};
        }
      }
      if (lone) {
        return {id: String(lone.id || ''), from: 0,
          until: Number(lone.seconds) || 0, at: t, index: loneAt, of: of};
      }
      return null;
    }
    if (t >= 0) {
      /* #1294: WHICHEVER TABLE CAN BE CHECKED AGAINST THE SOUND.
       *
       * liveStream.rows carry {id, from, until} and no media - probed
       * on the tablet, that is the whole of streamKeys - so #1287's
       * file guard above can never fire for them. When the sounding
       * file moves on and stream_now has not, the old burst's window
       * brackets the new file's currentTime and lights a row that is
       * not being said, for the length of the clip: 12 of the 19 wrong
       * samples measured were more than two seconds in, which is what
       * separates this from the mark merely lagging.
       *
       * The feed's rows carry clip_media, so when we know the name of
       * what is sounding they are the table that can be held to it.
       * Where the two describe the same file they agree to three
       * decimals, so this is a change of ORDER, not of arithmetic. */
      var fed = [];
      try { fed = (root.PineStationFeed.rows() || []); } catch (e1) { fed = []; }
      if (file && fed.length) {
        var named = within(fed, fed.length);
        if (named) return named;
      }
      var seat = within(rows, rows.length);
      if (seat) return seat;
      /* #1278: A CLIP OF ITS OWN IS STILL A LINE OF THE SCRIPT.
       *
       * This searched `liveStream.rows` and nothing else - one burst.
       * Anything that airs as its own single-row clip is not in that
       * list, so no window contained the position and the mark was
       * cleared. Measured over 827 sounding samples, the split was
       * perfect: `interject` lit correctly 0 times of 151, and
       * `station_id` 0 of 17, while every kind riding the welded burst
       * was lit sometimes. That is 20% of sounding samples guaranteed
       * wrong - and in 77% of the dark samples the line was already on
       * the page, so it was never the screenplay being stale.
       *
       * The feed's full row list is where those clips live. */
      /* [#1189] THE FILE-LESS SEARCH IS GONE.
       *
       * It used to be: with nothing sounding and no file to hold a row
       * to, search EVERY feed row for one whose window brackets the
       * estimate. #1247 is what that does. The station clock said 63.4s;
       * the desktop had already finished that burst and had no player at
       * all; `within(all)` found a row of block 6205 whose 63.4s window
       * matched - in a different file, 354 elements up the page - and lit
       * it for 1.7 seconds. An offset without a filename is not evidence
       * of anything, and two files agreeing about a number is a
       * coincidence, not a reading. Nothing replaces it: with no file
       * this road returns whatever speaking_now says, and that only ever
       * dresses the EXPECTED mark now. */
    }
    if (speakingNow && speakingNow.id) {
      return {id: String(speakingNow.id), from: 0, until: 0, at: t,
        index: -1, of: rows.length};
    }
    return null;
  }

  /* PULL THE ARITHMETIC BACK ONTO THE STATION'S TRUTH.
   *
   * Measured over 30 samples: the interpolation agreed with the station on
   * 28 and disagreed on 2, both at a burst boundary, by a second or so.
   * That is drift - our clock and the station's playout are not the same
   * clock, and `at` is the moment the burst was HANDED to the player, not
   * the moment sound left it.
   *
   * So `speaking_now` is used as a reference mark rather than a fallback.
   * When the poll says a different row is in the room, the offset is
   * nudged - not snapped - until the two agree. Nudging matters: a snap on
   * a four-second-old reading would jerk the highlight backwards every
   * poll, which looks worse than the drift it fixes. */
  function correct() {
    if (!speakingNow || !speakingNow.id || !liveStream) return;
    var rows = liveStream.rows || [];
    var want = String(speakingNow.id);
    var seat = -1;
    for (var i = 0; i < rows.length; i += 1) {
      if (String(rows[i].id || '') === want) { seat = i; break; }
    }
    if (seat < 0) return;
    var row = rows[seat];
    var t = streamAt();
    if (t < 0) return;
    if (t >= Number(row.from || 0) && t < Number(row.until || 0)) return;  /* agreed */
    /* How far off we are from the middle of the row the station names. */
    var aim = (Number(row.from || 0) + Number(row.until || 0)) / 2;
    var off = (aim - t) * 1000;
    if (Math.abs(off) > 30000) return;   /* a different burst entirely */
    /* Held SEPARATELY from the clock skew, which is re-read from
     * `server_ms` on every poll and would otherwise wipe this out four
     * seconds after it was learned. */
    /* #1267: AND IT IS NO LONGER CARRIED. Measured on the tablet
     * against the station, 21 samples where the room was saying a
     * named line: the highlight was the right line in 16, and in the
     * other 5 it was BEHIND - one entry twice, two once, three twice -
     * and never once ahead. A one-directional error is a bias, not
     * drift.
     *
     * This is why. `driftMs` starts at 0 on every new burst (the
     * subscriber resets it whenever `liveStream.at` moves), is only
     * touched when the interpolated position falls OUTSIDE the row the
     * station names, and then closes just HALF the gap. So each burst
     * began with the error back at zero and converged in halves, which
     * on lines of five to seven seconds means it is still catching up
     * when the burst ends.
     *
     * The comment above justified it by 2 disagreements in 30 samples
     * at burst boundaries. It is now costing 5 in 21 across the whole
     * line - the cure was worse than the fault.
     *
     * The station's own feed has no such term: sampler-feed.js reads
     * `Date.now() + skew` and picks the row whose window contains it,
     * full stop. With this gone the two arithmetics are identical, and
     * the page agrees with the feed by construction rather than by
     * chasing it. `off` is still measured and reported below, because a
     * number worth fixing is worth watching.
     */
    lastOffMs = off;
  }

  /* ONE line carries the mark. The class is removed from whatever had it
   * before rather than from everything, so a 283-element script does not
   * get walked four times a second. */
  var chasedFor = Object.create(null);           /* [#1189] id -> last chase */

  function chaseStalePage(id, node) {
    /* The resolver only calls markNow with a line read from the sounding
       file.  If that same line is still `prepared` in the screenplay, the
       durable air-log copy is behind the live feed.  Ask for one fresh
       composition now instead of waiting twenty seconds while the page
       unfolds a prepared block around the mark. */
    if (!node || !node.classList.contains('pending')
        || !PineScriptResolver.isLineId(id)) return false;
    var t = Date.now();
    if (t - chasedAt <= 3000 || t - Number(chasedFor[id] || 0) <= 20000) {
      return false;
    }
    chasedAt = t; chasedFor[id] = t;
    loadScreenplay(true);
    return true;
  }

  var markAuditAt = 0;
  var markAuditNode = null;
  function markNow(id) {
    if (id === nowLineId) {
      /* [#1189] RE-ASSERTED ON THE KEYED NODE. A repaint may have rebuilt
         the node without its mark; the id being unchanged is not the mark
         being present. */
      var same = id ? revealLine(id, true) : null;
      var now = Date.now();
      var indexed = !id || (same && lineNodes.get(String(id)) === same && same.isConnected);
      /* Repaint and identity changes get an immediate sweep; stable mounted
         lines only need a periodic audit for out-of-band marks. */
      if (!indexed || markAuditNode !== same || now - markAuditAt >= 1000
          || now < markAuditAt || (same && !same.classList.contains('sp-now'))) {
        var oldMarks = document.querySelectorAll('.sp-el.sp-now');
        for (var m = 0; m < oldMarks.length; m += 1) {
          if (oldMarks[m] === same) continue;
          oldMarks[m].classList.remove('sp-now');
          oldMarks[m].classList.remove('sp-feed-now');
          oldMarks[m].removeAttribute('aria-current');
        }
        markAuditAt = now;
        markAuditNode = same;
      }
      if (same) {
        if (!same.classList.contains('sp-now')) same.classList.add('sp-now');
        if (same.getAttribute('aria-current') !== 'true') {
          same.setAttribute('aria-current', 'true');
        }
      }
      chaseStalePage(id, same);
      return;
    }
    /* #1263: CLEAR EVERY MARK, not the one we remember.
     *
     * "it's highlighting multiple lines at the same time when it's
     *  broadcasting. When really I need it to highlight a single line."
     *
     * This used to un-mark only the node matching `nowLineId`, so any
     * path that cleared that variable WITHOUT repainting left its line
     * lit for ever and the next tick lit another beside it. There are
     * three such paths - the live chip, and the two view gestures added
     * in #1260 - and each tap stranded one more highlight.
     *
     * Only one line is ever being said, so only one may ever be marked.
     * Asking the document rather than trusting a remembered id makes
     * that true by construction, whatever else clears what. */
    var lit = document.querySelectorAll('.sp-el.sp-now');
    for (var i = 0; i < lit.length; i += 1) {
      lit[i].classList.remove('sp-now');
      lit[i].classList.remove('sp-feed-now');
      lit[i].removeAttribute('aria-current');
    }
    /* #1270: A MARK THAT DID NOT HAPPEN IS NOT REMEMBERED.
     *
     * This used to write `nowLineId = id` and only THEN look for the
     * node, returning quietly when the line was not on the page yet -
     * which happens constantly, because the station moves to a line
     * the moment it airs and the screenplay is only re-read every
     * twenty seconds. The id was now recorded as marked when nothing
     * had been marked, so every later tick hit `id === nowLineId` at
     * the top and returned. The highlight then sat on the PREVIOUS
     * line until the station moved again - which is the one-to-three
     * entry lag measured on the tablet, always behind and never ahead.
     *
     * It was masked until now: paintScript cleared nowLineId on every
     * repaint, so the mark was forced to re-seat three times a minute.
     * #1269 stopped rebuilding the page and the mask went with it.
     *
     * So the node is found FIRST. If the line has not arrived yet the
     * id is left unset and the next tick - a quarter of a second - has
     * another go, which is also what makes the view seat itself on
     * mount instead of sitting at the top of a 72,000px script.
     */
    var node = id ? revealLine(id, true) : null;
    if (id && !node) {
      /* #1271: AND THE PAGE GOES AND GETS IT.
       *
       * The line the room is saying can only be marked if it is ON the
       * page, and the script is re-read every twenty seconds - so a
       * line that aired since the last read waits, and the highlight
       * sits on the one before it. Measured on the tablet: correct
       * within 3 seconds at some changes and 7 at others, always one
       * line behind, always catching up in the end. The wait was the
       * whole of it.
       *
       * Being unable to find the line IS the signal that the script is
       * stale, so it asks for a fresh one there and then, at most once
       * every three seconds. Nothing else in the view has to know. */
      nowLineId = '';
      /* [#1189] A CHASE IS FOR A LINE THE PAGE SHOULD HAVE. An `observed:`
         pseudo-id, a short board id or a row the feed does not know can
         never arrive in a fresh screenplay, and chasing them forced a full
         re-read every three seconds for the length of every unadmitted
         clip - the document revisions that churned under the reader. A
         real line id is chased once per twenty seconds. */
      var t = Date.now();
      if (PineScriptResolver.isLineId(id) && t - chasedAt > 3000
          && t - Number(chasedFor[id] || 0) > 20000) {
        chasedAt = t; chasedFor[id] = t;
        loadScreenplay(true);
      }
      return;
    }
    nowLineId = id || '';
    markAuditAt = Date.now();
    markAuditNode = node;
    if (!node) return;
    node.classList.add('sp-now');
    node.setAttribute('aria-current', 'true');
    chaseStalePage(id, node);
    segFollow(node.getAttribute('data-seg') || '');          /* #1285 */
    if (follow) {
      /* Move only when needed, by one measured delta. Smooth animations
         overlapped the next poll and made anchor restoration count their
         unfinished travel a second time; an exact nearest-edge seat has no
         in-flight state for a repaint to race. */
      moveScript('follow', function (pane) { seatLineNearest(pane, node); });
    }
  }

  function seconds(v) {
    if (!isFinite(v)) return '—';
    return (v < 10 ? v.toFixed(1) : String(Math.round(v))) + 's';
  }

  /* WHY IT IS NOT SPEAKING YET, in one line.
   *
   * "I want to be able to see what is causing it to delay or what is
   * happening with its processing."
   *
   * Everything below already rides in the feed poll this view subscribes
   * to, so the readout costs no request. The order is deliberate: what the
   * room can hear beats what the desk is doing, and a named blocker beats
   * a count. */
  function status() {
    var row = activeRow();
    /* [#1189] HOW LONG A HELD MARK HAS BEEN HELD, said the way a person
       says it. #1210's strip read "AIR PAUSED - HELD - holding the last
       read line for 22189s", which is a number nobody reads as six
       hours. Seconds while it is fresh; the clock time and the minutes
       once it is not. Declared here so both roads out of status() -
       paused, and nothing sounding - tell the age the same way. */
    function heldWords(ageS, atMs) {
      var age = Number(ageS);
      if (!isFinite(age) || age < 0) return 'a moment ago';
      if (age < 90) return Math.round(age) + 's ago';
      var when = Number(atMs) - age * 1000;
      var stamp = '';
      if (isFinite(when) && when > 0) {
        try { stamp = new Date(when).toTimeString().slice(0, 8); } catch (e) { stamp = ''; }
      }
      var mins = Math.round(age / 60);
      var words = mins + (mins === 1 ? ' minute' : ' minutes') + ' ago';
      return stamp ? stamp + ' (' + words + ')' : words;
    }
    /* [#1189] #1210: the paused strip said "HELD" over a line lit six
       hours earlier and never said how old it was. It says so now, and
       the mark itself is let go after ten minutes
       (PineScriptResolver.CARRY_MAX_S). */
    if (stationPaused) {
      var dPause = lastDecision;
      return {state: 'paused', text: 'air paused \u2014 nothing is going out'
        + ((dPause && dPause.carried_id)
            ? ' \u2014 held since ' + heldWords(dPause.carried_age_s, dPause.at_ms)
            : '')};
    }

    /* A CARRIED MARK IS NOT "ON AIR". It is the last line this view could
       prove, held up while the evidence is missing, and saying "4.2s left"
       over it would be inventing a countdown for audio nobody can see. */
    /* [#1189] NOTHING IS ON AIR. Say what the page can honestly say: what
       is sounding that it cannot name, what it last heard, or what the
       station clock expects - each labelled as that, never as air. */
    if (!row && lastDecision) {
      var d0 = lastDecision, chip = playoutWord();
      if (chip) chip = ' \u2014 ' + chip;
      if (d0.sync === 'read-unmapped') {
        return {state: 'wait', text: (d0.why || 'sounding something the page does not name') + chip};
      }
      if (d0.carried_id) {
        return {state: 'wait', text: 'last heard ' + lineWho(d0.carried_id) + '\u2014 '
          + heldWords(d0.carried_age_s, d0.at_ms) + '; ' + (d0.why || 'nothing sounding') + chip};
      }
      if (d0.expected_id) {
        return {state: 'wait', text: 'expected ' + lineWho(d0.expected_id) + '\u2014 '
          + (d0.source === 'estimated' ? 'estimated from the station clock, no playhead'
             : (d0.why || 'no playhead')) + chip};
      }
    }
    if (row && row.carried) {
      return {state: 'wait', text: 'holding the last read line \u2014 ' + syncWhy};
    }

    if (row && row.until > row.from) {
      var left = row.until - row.at;
      var node = document.querySelector('.sp-el[data-line="' + row.id + '"]');
      var who = '';
      if (node) {
        var prev = node.previousElementSibling;
        if (prev && prev.classList.contains('sp-character')) who = prev.textContent + ' · ';
      }
      var tail = '';
      if (row.index >= 0 && row.of) {
        var rest = row.of - row.index - 1;
        tail = rest > 0 ? ' · ' + rest + ' more in this burst' : ' · last of the burst';
      }
      return {state: 'air', text: who + 'on air · ' + seconds(Math.max(0, left))
        + ' left of ' + seconds(row.until - row.from) + tail
        + (playoutWord() ? ' — ' + playoutWord() : '')};                     /* [#1189] */
    }

    if (row && row.id) return {state: 'air', text: 'on air' + (playoutWord() ? ' — ' + playoutWord() : '')};

    /* Nothing in the room. Say what the booth is doing about it. */
    var f = flow || {};
    if (f.render_waiting) {
      return {state: 'work', text: 'written, waiting on the voice — '
        + f.render_waiting + ' line' + (f.render_waiting === 1 ? '' : 's')
        + ' in the render queue'};
    }
    if (f.delivery_waiting) {
      return {state: 'work', text: 'voiced, waiting to be handed to air — '
        + f.delivery_waiting + ' waiting'};
    }
    if (f.writing) return {state: 'work', text: 'the room is writing the next round'};
    if (f.ad_cover) return {state: 'work', text: 'an ad is covering the gap'};

    /* A BLOCKER IS ONLY A BLOCKER IF IT BLOCKS.
     *
     * `blockers` carries all-clears too - measured live, the only entry was
     * "continuity reserve is healthy" - and `tint_hold` is TRUE at rest, so
     * an earlier draft of this line read "holding for the tint lane to
     * finish a pass" permanently, over ordinary music. A readout that says
     * the same worried thing all day teaches the operator to ignore it. */
    var blockers = (f.blockers || []).filter(function (b) {
      var t = String(b || '').toLowerCase();
      return t && t.indexOf('healthy') < 0 && t.indexOf('is fine') < 0
        && t.indexOf('no shortage') < 0 && t.indexOf(' ok') < 0;
    });
    if (blockers.length) return {state: 'wait', text: 'held: ' + blockers[0]};

    /* Nothing is wrong: it is a music bed, and the only question worth
     * answering is when the pair are back. */
    var rest = 'music';
    if (typeof f.talk_next_in === 'number' && f.talk_next_in > 0) {
      rest += ' — the pair are back in ' + seconds(f.talk_next_in);
    } else if (typeof f.ready === 'number' && typeof f.target === 'number') {
      rest += ' — ' + f.ready + ' rounds banked against a target of ' + f.target;
    }
    return {state: 'idle', text: rest};
  }

  /* WHAT THE MARK IS STANDING ON, in two words and a reason.
   *
   * The audit's warning, kept literally: "Preserve the last trustworthy
   * position when playback evidence is unavailable and expose the
   * synchronization state. Merely preventing a backward visual movement
   * would hide an audio fault." So a carried mark is drawn differently
   * from a live one and says how old it is. */
  function paintSync(row) {
    var node = el('spSync');
    if (!node) return;
    var carried = !!(row && row.carried);
    var state = String(syncState || 'held');
    var name = PineScriptCues.say({sync: state});
    var why = String(syncWhy || '');
    if (carried && lastGood && lastGood.at) {
      var age = Math.max(0, Math.round((Date.now() - lastGood.at) / 1000));
      why = (why ? why + ' - ' : '') + 'holding the last read line for ' + age + 's';
    }
    if (admitMap && admitMap.ok && !admitMap.count && state !== 'paused') {
      why = why || admitMap.why;
    }
    if (node.dataset.sync !== state) node.dataset.sync = state;
    node.classList.toggle('sp-sync-carried', carried);
    /* AND ON THE MARK ITSELF. A highlight held up without evidence must
       not be drawn identically to one the sound is standing behind - that
       is precisely the "hide an audio fault" the audit refuses. */
    try {
      var mapped = !!(admitMap && admitMap.ok && admitMap.count);
      if (host) {
        host.classList.toggle('sp-unsynced',
          mapped && !(state === 'read' || state === 'read-gap'));
      }
    } catch (err) { /* the strip still says it */ }
    paintPlayout(node);                                       /* [#1189] */
    var b = node.firstChild, i = node.lastChild;
    if (b && b.__text !== name) { b.__text = name; b.textContent = name; }
    if (i && i.__text !== why) { i.__text = why; i.textContent = why; }
  }

  function scheduledNow() {
    var now = Date.now() / 1000;
    var fallback = null;
    for (var h = 0; h < planHours.length; h += 1) {
      var entries = (planHours[h] && planHours[h].entries) || [];
      for (var i = 0; i < entries.length; i += 1) {
        var entry = entries[i] || {};
        if (String(entry.state || '') === 'on air') return entry;
        var start = Number(entry.start) || 0;
        var end = Number(entry.deadline) || (start
          + Math.max(15, (Number(entry.minutes) || 1) * 60));
        if (start && start <= now && now < end) fallback = entry;
      }
    }
    return fallback;
  }

  function scheduledAfter(current) {
    var rows = [];
    planHours.forEach(function (page) {
      rows = rows.concat((page && page.entries) || []);
    });
    rows.sort(function (a, b) { return (Number(a.start) || 0) - (Number(b.start) || 0); });
    var after = current ? Number(current.deadline) || Number(current.start) || 0
      : Date.now() / 1000;
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i] === current) continue;
      if ((Number(rows[i].start) || 0) >= after - 1
          && String(rows[i].state || '') !== 'aired') return rows[i];
    }
    return null;
  }

  function monitorMessage(stage, detail, state, flow) {
    return {stage: stage, detail: detail, status: state || '',
      at: Date.now() / 1000, _flow: flow || null};
  }

  var monitorPrint = '';
  function paintOrchestratorMonitor(line, current) {
    var track = line.querySelector('.sp-now-orch-track');
    if (!track) return;
    var next = scheduledAfter(current);
    var messages = [];
    if (next) {
      var script = next.script || {};
      var turns = (script.turns || []).length;
      var drafts = Number(script.drafts) || 0;
      if (turns) messages.push(monitorMessage('ready', 'Next line ready: '
        + String(next.label || next.kind || 'segment') + ' - ' + turns
        + (turns === 1 ? ' line banked' : ' lines banked'), 'ready', next));
      else if (drafts) messages.push(monitorMessage('drafts', drafts
        + (drafts === 1 ? ' draft waiting for ' : ' drafts waiting for ')
        + String(next.label || next.kind || 'the next segment'), 'waiting', next));
      else messages.push(monitorMessage('issue', String(next.label || next.kind
        || 'the next segment') + ' has no prepared dialogue yet', 'behind', next));
    }
    if (current) {
      var deadline = Number(current.deadline) || 0;
      var remaining = deadline ? deadline - Date.now() / 1000 : 0;
      messages.push(monitorMessage(remaining < -2 ? 'behind' : 'timing',
        remaining < -2 ? 'The broadcast has run past this segment window'
          : 'The broadcast is running on time', remaining < -2 ? 'behind' : 'on time', current));
    }
    try {
      var history = root.PineConsoleLine && root.PineConsoleLine.history
        ? root.PineConsoleLine.history().slice(0, 4) : [];
      history.forEach(function (item) { messages.push(item); });
    } catch (err) { /* readiness remains useful on its own */ }
    if (!messages.length) messages.push(monitorMessage('orchestrator',
      'Waiting for the running order', 'waiting'));
    var key = messages.map(function (item) {
      return String(item.stage || '') + ':' + String(item.detail || '');
    }).join('|');
    if (key === monitorPrint) return;
    monitorPrint = key;
    track.replaceChildren();
    messages.concat(messages).forEach(function (item) {
      var button = make('button', 'sp-now-orch-message', '');
      button.type = 'button';
      button.dataset.status = String(item.status || '');
      button.appendChild(make('b', '', String(item.stage || 'orchestrator')));
      button.appendChild(make('span', '', String(item.detail || '')));
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        if (root.PineConsoleTrace && root.PineConsoleTrace.open) {
          root.PineConsoleTrace.open(item);
        }
      });
      track.appendChild(button);
    });
    line.style.setProperty('--sp-monitor-time', Math.max(24,
      Math.min(80, key.length / 7)) + 's');
  }

  function paintStatus(row) {
    var line = el('spNow');
    if (!line) return;
    var got = status();
    var scheduled = scheduledNow();
    var segment = activeSegment(row);
    var name = scheduled ? String(scheduled.label || scheduled.kind || 'segment')
      : (segment && segment.heading ? String(segment.heading) : 'Active broadcast');
    var start = Number(scheduled && scheduled.start) || Number(row && row.from) || 0;
    var end = Number(scheduled && scheduled.deadline) || Number(row && row.until) || 0;
    var span = end - start;
    var now = Date.now() / 1000;
    var progress = span > 0 ? Math.max(0, Math.min(1, (now - start) / span)) : 0;
    var left = span > 0 ? Math.max(0, Math.ceil(end - now)) : 0;
    var leftText = span > 0 ? (left >= 60
      ? Math.floor(left / 60) + ':' + ('0' + (left % 60)).slice(-2)
      : left + 's') : '';
    var nameNode = line.querySelector('.sp-now-segment-name');
    var leftNode = line.querySelector('.sp-now-segment-left');
    var cueNode = line.querySelector('.sp-now-cue');
    if (nameNode && nameNode.textContent !== name) nameNode.textContent = name;
    if (leftNode) {
      var statusText = leftText ? leftText + ' left' : got.text;
      if (leftNode.textContent !== statusText) leftNode.textContent = statusText;
    }
    if (cueNode) {
      var active = row && row.id ? lineNode(String(row.id)) : null;
      var item = active && active.pineItem;
      var cueText = active && item
        ? 'ON AIR  ' + lineWho(String(row.id)) + String(item.text || '')
        : got.text;
      if (cueNode.textContent !== cueText) cueNode.textContent = cueText;
      if (cueNode.disabled !== !active) cueNode.disabled = !active;
      var cueLine = active ? String(row.id) : '';
      if (cueNode.dataset.line !== cueLine) cueNode.dataset.line = cueLine;
      var cueTitle = active ? 'Return to the cue currently playing' : got.text;
      if (cueNode.title !== cueTitle) cueNode.title = cueTitle;
    }
    var run = Math.round(progress * 100) + '%';
    if (line.style.getPropertyValue('--sp-segment-run') !== run) {
      line.style.setProperty('--sp-segment-run', run);
    }
    if (scheduled || (segment && segment.heading)) {
      var segmentId = String((scheduled && (scheduled.slot_id || scheduled.ordinal))
        || (segment && (segment.seg || segment.block)) || '');
      if (line.dataset.segment !== segmentId) line.dataset.segment = segmentId;
      var lineTitle = 'Active segment: ' + name
        + '. Tap for the hour and station calendar.';
      if (line.title !== lineTitle) line.title = lineTitle;
    } else {
      if (line.dataset.segment) delete line.dataset.segment;
      if (line.title !== 'Tap for the hour and station calendar.') {
        line.title = 'Tap for the hour and station calendar.';
      }
    }
    if (line.dataset.state !== got.state) line.dataset.state = got.state;
    paintOrchestratorMonitor(line, scheduled);
  }

  /* The 250 ms heartbeat: move the mark, move the readout. Nothing here
   * touches the network. */
  /* #1295: HOW MUCH OF THIS CLIP IS LEFT, drawn on the line itself.
   *
   * Set as a custom property and an attribute, never as a child node:
   * the reconciler re-dresses a changed line with textContent, so a
   * child span would be wiped every repaint. The CSS paints the bar
   * off --sp-run and the countdown off data-left.
   *
   * A row with no usable window (an interject is a clip of one line
   * and carries neither end) gets no bar rather than a wrong one. */
  var runNode = null;

  function markRun(row) {
    var node = row && row.id ? lineNode(row.id) : null;
    if (runNode && runNode !== node) {
      runNode.style.removeProperty('--sp-run');
      runNode.removeAttribute('data-left');
    }
    runNode = node;
    if (!node || !row) return;
    var span = Number(row.until) - Number(row.from);
    var gone = Number(row.at) - Number(row.from);
    if (!isFinite(span) || span <= 0 || !isFinite(gone)) {
      node.style.removeProperty('--sp-run');
      node.removeAttribute('data-left');
      return;
    }
    /* #1428: and the same here - 52 writes of data-left in eight
       seconds, 10 of them a change. The countdown moves once a second;
       tick does not. --sp-run was a percentage to ONE DECIMAL, so it
       differed on paper every tick even when the bar could not move a
       pixel; whole percent is finer than it can render. */
    var run = Math.max(0, Math.min(1, gone / span));
    var runPct = Math.round(run * 100) + '%';
    if (node.style.getPropertyValue('--sp-run') !== runPct) {
      node.style.setProperty('--sp-run', runPct);
    }
    var left = Math.max(0, Math.round(span - gone));
    var leftText = left >= 60
      ? (Math.floor(left / 60) + ':' + ('0' + (left % 60)).slice(-2))
      : (left + 's');
    if (node.getAttribute('data-left') !== leftText) {
      node.setAttribute('data-left', leftText);
    }
  }

  function scriptVisible(node, hidden) {
    if (hidden || !node) return false;
    if (node.classList && node.classList.contains('pine-view-host')) {
      return node.classList.contains('open');
    }
    return node.offsetParent !== null;
  }

  function tick() {
    if (!scriptVisible(host, document.hidden)) return;
    rejectionStep();
    if (!rejectionSelection && Date.now() - rejectionHeadAt > REJECTION_REFRESH_MS) {
      rejectionLoad(true);
    }
    var row = activeRow();
    /* The bounded ring of what the mark did and why - the incident report
       carries it, so a backward movement can be told apart from a document
       reflow and from a gap in the evidence. */
    var seen = syncRing[syncRing.length - 1];
    var mine = {at: Date.now(), sync: syncState,
      line: row ? String(row.id || '') : '',
      occurrence: row ? String(row.occurrence_id || '') : '',
      position: row && row.position !== undefined ? row.position : null,
      carried: !!(row && row.carried)};
    if (!seen || seen.sync !== mine.sync || seen.line !== mine.line
        || seen.occurrence !== mine.occurrence) {
      syncRing.push(mine);
      if (syncRing.length > SYNC_RING_MAX) syncRing.shift();
    }
    paintSaying(row);                                         /* #1298 */
    paintLiveCueWindow(row);
    if (Date.now() - readinessClockAt >= 1000) {
      readinessClockAt = Date.now();
      paintReadiness();
    }
    placeMarks(lastDecision);                                /* [#1189] */
    markRun(row);                                            /* #1295 */
    markFeedLive(row ? row.id : '');                          /* #1279 */
    /* #1286: say when the room is quiet, instead of leaving a page full
       of `pending` and `tinted` marks to be read as though one of them
       were live. */
    try {
      /* #1294: the PLAYER, not the row. This read activeRow(), which
         falls back to speaking_now, so quiet stayed off for a second
         or two after a clip ended - 22 of 348 silent samples. What
         "quiet" means is that nothing is sounding, and there is an
         element that knows. */
      host.classList.toggle('sp-quiet', !soundingPlayer() && !(row && row.id));
    } catch (err) { /* the mark still stands on its own */ }
    paintStatus(row);
    paintSync(row);
    /* [#1189] ONE TIMER. The recorder used to sample on its own 250ms
       interval, a quarter-phase away from this one, so every line change
       was recorded once with the old highlight and the new active - the
       "highlighted identity differs from the client active-line identity"
       finding in all sixteen captures was that phase, not a fault. It
       samples here, after placement, and the lit line is kept in view. */
    var nowMs = Date.now();
    if (nowMs - sampledAt >= MOTION_MS - 20) {
      sampledAt = nowMs;
      try { sampleMotion(); } catch (e) { /* the ring is a courtesy */ }
    }
    keepLitInView('tick');
    playoutPoll();
  }
  var sampledAt = 0;                              /* [#1189] */

  /* #1303b: the row the sampler's own sourceFor() expects. A clip line
     carries its url and is taken exactly; a spoken line carries its id
     and the clip route cuts it out of the welded round. */
  function samplerRow(item) {
    if (!item) return null;
    var id = String(item.line || item.id || '');
    var url = String(item.clip || '');
    if (!id && !url) return null;
    var row = {id: id, text: String(item.text || ''),
               who: String(item.name || item.who || '')};
    if (url) { row.url = url; row.sfx = true; }
    return row;
  }

  function padRow(item) {
    var row = samplerRow(item);
    if (!row) return null;
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') return null;
    try {
      if (typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        return null;                 /* nothing behind it: no button */
      }
    } catch (err) { return null; }
    var btn = make('button', 'sp-btn wide', 'Send to a sampler pad');
    btn.title = 'Put this on the first free pad of the sampler';
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = 'taking it...';
      Promise.resolve(sampler.grab(row)).then(function (got) {
        var ok = got && got.ok;
        btn.textContent = ok ? 'on a pad' : ((got && got.why) || 'it refused');
        btn.disabled = !!ok;
        if (!ok) setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      }).catch(function (err) {
        btn.textContent = 'it refused: ' + (err && err.message);
        setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      });
    });
    return btn;
  }

  function jumpToLine(id) {
    if (!id) return;
    var node = revealLine(id, false);
    if (!node) return;
    moveScript('jump', function () {
      node.scrollIntoView({block: 'center'});
    });
    node.classList.add('flash');
    setTimeout(function () { node.classList.remove('flash'); }, 1200);
  }

  /* A PRESS ON WHAT IS PLAYING MEANS FOLLOW THE AIR AGAIN.
   *
   * The live strip used to call jumpToLine(), which moved once but left
   * `follow` false after a hand scroll or crawl. The next spoken line
   * therefore advanced without the reader, making the strip look dead.
   * This is one command shared by the strip and the status line: stop the
   * competing crawl, reopen the live segment, center the current admitted
   * line, and leave following armed for every line after it. */
  function resumeAirFollow(reason) {
    if (crawlStop) crawlStop();
    follow = true;
    adrift = 0;
    keptAt = 0;
    var chip = el('spNow');
    if (chip) chip.classList.remove('adrift');

    var row = activeRow();
    var id = String((row && row.id) || '');
    if (!id) return false;
    var node = revealLine(id, true);
    if (!node) {
      /* The station may have admitted a line since the last document
       * read. Collect the fresh page now; markNow will seat it on the
       * first tick after paint. */
      nowLineId = '';
      loadScreenplay(true);
      return false;
    }

    var seg = String(node.getAttribute('data-seg') || '');
    if (seg) {
      folded[seg] = false;
      delete byHand[seg];
      if (liveSeg !== seg) segFollow(seg);
      else segApply(false);
    }
    nowLineId = '';
    markNow(id);
    moveScript('jump-to-air:' + (reason || 'control'), function (pane) {
      var lip = pane.getBoundingClientRect();
      var seat = node.getBoundingClientRect();
      pane.scrollTop = Math.max(0, pane.scrollTop + seat.top - lip.top
        - Math.max(0, (lip.height - seat.height) / 2));
    });
    node.classList.add('flash');
    setTimeout(function () { node.classList.remove('flash'); }, 1200);
    return true;
  }

  /* Tap a line: what it is, and what can be done with it. */
  function openLine(item, node) {
    pinned = item;
    document.querySelectorAll('.sp-el.picked').forEach(function (n) {
      n.classList.remove('picked');
    });
    node.classList.add('picked');
    var box = el('spDetail');
    if (!box) return;
    box.hidden = false;
    box.replaceChildren();

    box.appendChild(make('b', 'sp-detail-who', item.name || item.who || item.tag || 'the station'));
    box.appendChild(make('p', 'sp-detail-text', item.text || ''));

    var facts = [];
    if (item.round) facts.push(item.round);
    if (item.kind) facts.push(item.kind);
    if (item.engine) facts.push(item.engine);
    if (item.seconds) facts.push(Number(item.seconds).toFixed(1) + 's');
    if (item.tinted) facts.push('tinted');
    if (item.aired) facts.push(item.aired === 'stream' ? 'aired' : item.aired);
    box.appendChild(make('i', 'sp-detail-facts', facts.join('  ·  ')));

    var note = make('textarea', 'sp-note');
    note.placeholder = 'A note, or how this should have been said...';
    box.appendChild(note);

    var row = make('div', 'sp-detail-row');

    var keep = make('button', 'sp-btn wide', 'Keep the note');
    keep.addEventListener('click', function () {
      sendNote(item, note.value, keep);
    });
    row.appendChild(keep);

    /* #1303b: ASSIGN IT TO A PAD.
     *
     * Through PineSampler.grab, the published seam - whose own comment
     * says it exists so "another view can GREY ITS OWN BUTTON with the
     * same answer this one uses, rather than guessing from `aired` -
     * which is the exact mistake that once offered 7 of ~220 takeable
     * moments". So this asks takeable() and simply is not there when
     * there is nothing behind the line. */
    var take = padRow(item);
    if (take) row.appendChild(take);

    var back = make('button', 'sp-btn wide', 'Send to the recording room');
    /* Honest about the limit rather than failing in the operator's hand:
     * the return path needs a round that is still on the shelf. */
    back.title = 'Asks the writers to do this line again, with your note '
      + 'above it. Only possible while the round it belongs to is still on '
      + 'the shelf.';
    back.addEventListener('click', function () { sendBack(item, note.value, back); });
    row.appendChild(back);

    var clip = make('button', 'sp-btn wide', 'Hear it');
    clip.disabled = !item.clip;
    clip.addEventListener('click', function () { hear(item, clip); });
    row.appendChild(clip);

    box.appendChild(row);
    var close = make('button', 'sp-detail-close', '✕');
    close.addEventListener('click', function () { box.hidden = true; });
    box.appendChild(close);
  }

  function sendNote(item, text, button) {
    if (!text.trim()) { button.textContent = 'write something first'; return; }
    var was = button.textContent;
    button.textContent = 'keeping...';
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'line', target_id: item.line || item.id, text: text,
      who: 'operator'
    }).then(function () {
      button.textContent = 'kept';
      setTimeout(function () { button.textContent = was; }, 1600);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function sendBack(item, text, button) {
    var was = button.textContent;
    button.textContent = 'sending...';
    /* The note first, so the request and the reason are stored together
     * even if the rewrite is refused. */
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'rework', target_id: item.line || item.id,
      text: text || 'Do this one again.', who: 'operator'
    }).then(function () {
      button.textContent = 'asked';
      setTimeout(function () { button.textContent = was; }, 1800);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function hear(item, button) {
    if (!item.clip) return;
    var was = button.textContent;
    button.textContent = 'fetching...';
    var audio = new Audio(item.clip);
    audio.play().then(function () { button.textContent = was; },
      function () { button.textContent = 'would not play'; });
  }

  /* ------------------------------------------------------------- build */

  function build(node) {
    host = node;
    host.classList.add(HOST_CLASS);
    host.replaceChildren();

    var left = make('div', 'sp-left');
    left.appendChild(buildRejectionStrip());
    left.appendChild(buildBar());            /* 1 2 3 */
    var treeRow = make('div', 'sp-treerow');
    treeRow.appendChild(buildTree());        /* 4 */
    treeRow.appendChild(buildSaying());      /* #1298 */
    left.appendChild(treeRow);
    left.appendChild(buildPanel());
    left.appendChild(buildPlayer());         /* 5 */
    /* [#1386] THE FEED HAS TWO FACES.
     *
     * "I want to be able to toggle feed view between being feed view and
     *  technical view which is what it jumps into when i select any
     *  element in the script view."
     *
     * Feed is what the station is DOING. Technical is where any of it
     * CAME FROM - the same pane, the same place on the glass, so tracing
     * a line does not take the show off the screen. Tapping a name in the
     * script flips it here and traces that line; the toggle flips it back
     * and the feed carries on where it was. */
    var feedHead = make('div', 'sp-feedhead');
    var feedName = make('b', '', 'Feed');
    feedHead.appendChild(feedName);
    var feedWhy = make('i', 'sp-feedwhy', 'everything the station is doing');
    feedHead.appendChild(feedWhy);
    var feedFlip = make('button', 'sp-feedflip', 'technical');
    feedFlip.title = 'Trace where any of this came from. Tap a name in the '
      + 'script to trace that line.';
    feedFlip.addEventListener('click', function () {
      technicalToggle();
    });
    feedHead.appendChild(feedFlip);
    var wideFlip = make('button', 'sp-feedflip sp-techwide',
      techWide ? 'in column' : 'full width');
    wideFlip.addEventListener('click', function () {
      /* Pressing this is also asking to SEE it - going wide with the pane
         still shut would look like a button that does nothing. */
      if (!techOn) { technicalToggle(); }
      techWideSet(!techWide);
    });
    feedHead.appendChild(wideFlip);
    left.appendChild(feedHead);
    var feed = make('div', 'sp-feed');       /* 6 */
    feed.id = 'spFeed';
    feedCrawlStart(feed);
    feed.addEventListener('scroll', function () {
      feedStick = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
    });
    left.appendChild(feed);

    var right = make('div', 'sp-right');     /* 7 */
    var top = make('div', 'sp-script-top');
    var head = make('div', 'sp-scripthead');
    head.id = 'spScriptName';
    head.appendChild(make('b', '', 'The script'));
    head.appendChild(make('i', 'sp-scriptwhy', ''));
    head.lastChild.id = 'spScriptHead';
    /* #1164: "I want to be able to tap and hold on the name of the
       script as being run for that particular session and I want a
       drop-down menu that comes down". The same holdOpen() the SFX
       button, the caution button and the report icon are already on -
       one hold gesture in this file, not four of them drifting apart.
       A short tap never opens it; a short tap while it IS open puts it
       away, which is the toggle a menu on a name ought to have. */
    head.setAttribute('role', 'button');
    head.setAttribute('tabindex', '0');
    head.setAttribute('aria-haspopup', 'menu');
    head.setAttribute('aria-expanded', 'false');
    head.title = 'Tap: the full itinerary for this hour. Hold (or right-click):'
      + ' complain, mark an issue, report a missing segment';
    holdOpen(head, function () { headerOpen(head); });
    head.addEventListener('click', function () {
      if (head.pineHeld) return;              /* the hold has just answered */
      /* [#1235] A tap used to do nothing here but shut #1164's
         menu again. It opens the hour's running order now; the
         hold still raises the report menu, untouched. */
      if (el(HEADER_MENU_ID)) { headerClose(); return; }
      itineraryOpen();
    });
    /* At the desk there is a keyboard, and a role="button" that cannot
       be worked from it is a button in name only. */
    head.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
      ev.preventDefault();
      if (el(HEADER_MENU_ID)) headerClose();
      else headerOpen(head);
    });
    var titleRow = make('div', 'sp-script-title-row');
    var promptDock = make('div', 'sp-prompt-dock');
    titleRow.appendChild(head);
    titleRow.appendChild(promptDock);
    top.appendChild(titleRow);
    /* One line, console-shaped, directly under the heading: what is
       happening with the line that is being said. */
    var now = make('div', 'sp-now-line');
    now.id = 'spNow';
    now.dataset.state = 'idle';
    var segmentMonitor = make('div', 'sp-now-segment');
    segmentMonitor.appendChild(make('b', 'sp-now-segment-name', 'Active broadcast'));
    segmentMonitor.appendChild(make('span', 'sp-now-segment-left', 'waiting for timing'));
    var cue = make('button', 'sp-now-cue', 'Waiting for the next cue');
    cue.type = 'button';
    cue.disabled = true;
    cue.addEventListener('click', function (event) {
      event.stopPropagation();
      resumeAirFollow('current cue', cue.dataset.line || nowLineId);
    });
    segmentMonitor.appendChild(cue);
    var orchestratorMonitor = make('div', 'sp-now-orch');
    orchestratorMonitor.setAttribute('aria-label', 'Orchestrator status');
    orchestratorMonitor.appendChild(make('div', 'sp-now-orch-track'));
    now.appendChild(segmentMonitor);
    now.appendChild(orchestratorMonitor);
    var liveSequence = make('div', 'sp-live-sequence');
    liveSequence.id = 'spLiveSequence';
    liveSequence.hidden = true;
    liveSequence.setAttribute('aria-label', 'Live scripted event sequence');
    /* THE SYNCHRONIZATION STATE, said out loud.
       A held mark and a live mark must not look the same. */
    var sync = make('div', 'sp-sync');
    sync.id = 'spSync';
    sync.dataset.sync = 'held';
    sync.appendChild(make('b', 'sp-sync-name', ''));
    sync.appendChild(make('i', 'sp-sync-why', ''));

    var readiness = make('section', 'sp-readiness');
    readiness.id = 'spReadiness';
    readiness.setAttribute('aria-label', 'Upcoming segment preparation');
    var readinessHead = make('div', 'sp-readiness-head');
    readinessHead.appendChild(make('b', '', 'Upcoming preparation'));
    var readinessSummary = make('span', 'sp-readiness-summary', 'Reading the running order');
    readinessSummary.id = 'spReadinessSummary';
    readinessHead.appendChild(readinessSummary);
    var runningOrder = make('button', 'sp-ready-order', 'Running order');
    runningOrder.type = 'button';
    runningOrder.addEventListener('click', function () { itineraryOpen(); });
    readinessHead.appendChild(runningOrder);
    readiness.appendChild(readinessHead);
    var readinessTrack = make('div', 'sp-readiness-track');
    readinessTrack.id = 'spReadinessTrack';
    readinessTrack.setAttribute('role', 'list');
    readiness.appendChild(readinessTrack);
    var readinessDetail = make('div', 'sp-readiness-detail');
    readinessDetail.id = 'spReadinessDetail';
    readinessDetail.hidden = true;
    readiness.appendChild(readinessDetail);
    var bands = make('div', 'sp-bands');
    var restore = make('div', 'sp-band-restore');
    restore.setAttribute('role', 'toolbar');
    restore.setAttribute('aria-label', 'Restore Script bands');
    var bandItems = {};
    function addBand(key, content, glyph) {
      var label = BAND_NAMES[key];
      var wrap = make('div', 'sp-band-row sp-band-' + key);
      var collapse = make('button', 'sp-band-collapse');
      collapse.type = 'button';
      collapse.title = 'Collapse ' + label;
      collapse.setAttribute('aria-label', 'Collapse ' + label);
      collapse.setAttribute('aria-controls', content.id);
      collapse.innerHTML = folderIcon('c:caret--left', label) || '&lt;';
      collapse.addEventListener('click', function (event) {
        event.stopPropagation();
        bandManager.set(key, true);
      });
      wrap.appendChild(collapse);
      wrap.appendChild(content);
      bands.appendChild(wrap);
      var reopen = make('button', 'sp-band-reopen');
      reopen.type = 'button';
      reopen.title = 'Restore ' + label;
      reopen.setAttribute('aria-label', 'Restore ' + label);
      reopen.setAttribute('aria-controls', content.id);
      reopen.innerHTML = folderIcon(glyph, label) || label;
      reopen.addEventListener('click', function () {
        bandManager.set(key, false);
      });
      restore.appendChild(reopen);
      bandItems[key] = {wrap: wrap, content: content,
        collapse: collapse, restore: reopen};
    }
    addBand('current', now, 'c:timer');
    addBand('sequence', liveSequence, 'c:script');
    addBand('sync', sync, 'c:waveform');
    addBand('readiness', readiness, 'c:calendar');
    var promptHistory = make('button', 'sp-band-reopen');
    promptHistory.type = 'button'; promptHistory.title = 'System prompt history';
    promptHistory.setAttribute('aria-label', 'System prompt history');
    promptHistory.setAttribute('aria-pressed', 'false');
    promptHistory.innerHTML = folderIcon('c:time', 'System prompt history') || 'History';
    promptHistory.addEventListener('click', function () {
      if (root.PinePromptHistory) root.PinePromptHistory.toggle(right, promptHistory, promptDock);
    });
    restore.appendChild(promptHistory);
    top.appendChild(bands);
    top.appendChild(restore);
    right.appendChild(top);
    bandManager = bandController(bands, restore, bandItems);

    var script = make('div', 'sp-script');
    script.id = 'spScript';
    script.addEventListener('scroll', function () {
      if (Date.now() < selfScrollUntil) return;   /* our own scroll, in flight */
      stick = script.scrollTop + script.clientHeight >= script.scrollHeight - 40;
      /* Scrolling by hand means "let me read"; following would yank the
         page back every quarter second. Tapping the readout resumes it. */
      /* #1282: TWICE, NOT ONCE. Following used to end the first time
         the lit node looked off-screen, which a long smooth scroll
         guarantees mid-flight. Two consecutive readings means a single
         unsettled frame cannot end it - but a real hand-scroll, which
         produces many, still does. */
      var node = nowLineId
        && document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (node) {
        var box = script.getBoundingClientRect();
        var seat = node.getBoundingClientRect();
        var here = seat.bottom > box.top && seat.top < box.bottom;
        if (here) { adrift = 0; follow = true; }
        else if ((adrift += 1) >= 2) { follow = false; }
      } else if (nowLineId === '') {
        /* #1270 leaves this empty while the line has not arrived. The
           old code reconsidered nothing here, so scrolling away during
           that window did not count as "let me read" and the page
           yanked back the moment the line landed. */
        if ((adrift += 1) >= 2) { follow = false; }
      }
      var chip = el('spNow');
      if (chip) chip.classList.toggle('adrift', !follow);
    });
    right.appendChild(script);

    /* #1260: DOUBLE-TAP THE SCRIPT TO READ IT PROPERLY.
     *
     * "If I double tap the script page, I want to also have the script
     *  show up in this view." - the full-page screenplay the desktop
     *  shows, on the glass, instead of a column beside the player.
     *
     * A class on the host, so the layout is CSS's business and nothing
     * here has to know about the other six regions. dblclick fires on
     * this WebView; the manual two-tap timer underneath it is for the
     * cases where a fast double touch is delivered as two taps and the
     * synthetic dblclick never arrives. */
    /* #1272: A SINGLE TAP DOES NOTHING, AND THAT IS THE POINT.
     *
     * "script view should only go fullscreen if i double tap the blank
     *  area of the script view. If i tripple tap it, show it with the
     *  colorings and display style of a script document so it can be
     *  easier on the eyes."
     *
     * The operator works this view with a thumb while the station is
     * playing - listening, reading, and grabbing clips onto sampler
     * pads - so a single stray tap on the margin must not throw the
     * pane into full screen underneath them. Nothing happens until a
     * second tap says it was meant.
     *
     *     two taps    full screen, on and off
     *     three taps  the script-document setting, on and off
     *
     * The count is held for one window after the LAST tap rather than
     * the first, so a deliberate triple is never cut short by the
     * double firing on its way past. */
    var tapTimer = null;
    var taps = 0;
    var TAP_WINDOW = 300;
    var PAPER = 'sp-look-paper';

    function reseat() {
      /* The pane changed shape, so the line that was centred no longer
         is. Re-seat rather than leave the reader stranded. */
      follow = true;
      nowLineId = '';
      try { tick(); } catch (e) { /* the change matters more */ }
    }
    function bigToggle() { host.classList.toggle('sp-big'); reseat(); }
    /* #1272: the script-document setting - paper, Courier, the standard
       measures, and each element coloured for what it IS. One setting
       that goes on and off, not a cycle: the operator asked for a look,
       not a carousel. */
    function paperToggle() { host.classList.toggle(PAPER); reseat(); }

    /* A tap on a LINE still opens that line - that is what the detail
     * panel is for and it predates this. These gestures belong to the
     * PANE: the margins, the gutters, the space between the speeches. */
    function onTap(ev) {
      var t = ev && ev.target;
      if (t && t.closest && t.closest('button, input, a, .sp-detail')) return;
      /* THE BLANK AREA ONLY. A tap on a line belongs to that line - it
         opens the detail panel, which is how a clip is inspected and
         sent to a pad - and must never be read as part of a gesture. */
      if (t && t !== script && t.closest && t.closest('.sp-el')) return;
      taps += 1;
      if (tapTimer) clearTimeout(tapTimer);
      tapTimer = setTimeout(function () {
        var count = taps;
        tapTimer = null;
        taps = 0;
        if (count === 2) bigToggle();
        else if (count >= 3) paperToggle();
        /* one tap: nothing at all */
      }, TAP_WINDOW);
    }
    script.addEventListener('click', onTap);

    /* --- THE CRAWL -------------------------------------------------
     *
     * "I want an icon that allows me to start it auto scrolling, but by
     *  default I want it to automatically be on the area that's actively
     *  airing. However, I do want a slider that allows me to choose the
     *  speed."
     *
     * Two different ways to move, and they must not fight: FOLLOW keeps
     * the live line in view and is the default; CRAWL walks the page at
     * a chosen rate for reading ahead. Starting the crawl stands follow
     * down, and tapping the live chip (which already exists) stands the
     * crawl down and goes back to the air. */
    var crawl = false;
    var crawlPx = 18;            /* pixels per second at the middle */
    var crawlLast = 0;
    var crawlOwed = 0;

    var tools = make('div', 'sp-crawl');
    var run = make('button', 'sp-crawl-go');
    run.type = 'button';
    run.textContent = '▶';           /* play; becomes pause when on */
    run.title = 'Auto-scroll the script';
    var rate = document.createElement('input');
    rate.type = 'range';
    rate.min = '1'; rate.max = '100'; rate.value = '30';
    rate.className = 'sp-crawl-rate';
    rate.title = 'How fast it scrolls';
    tools.appendChild(run);
    tools.appendChild(rate);
    /* #1289: the hour ahead, and which way to show it. */
    var ahead = make('button', 'sp-crawl-go sp-planway');
    ahead.type = 'button';
    ahead.textContent = '⎘';
    ahead.title = 'The hour ahead: below the script, or beside it';
    ahead.addEventListener('click', function (ev) {
      ev.stopPropagation();
      planLayout(planWay === 'below' ? 'beside' : 'below');
      ahead.classList.toggle('on', planWay === 'beside');
      loadPlan(true);
    });
    tools.appendChild(ahead);
    right.appendChild(tools);

    var plan = make('div', 'sp-plan');
    plan.id = 'spPlan';
    script.appendChild(plan);          /* 'below' is the default */

    function crawlRate() {
      /* 1..100 on the slider, about 2 to 220 px a second, curved so the
         slow half of the travel has real resolution - that is the half
         anybody reading along actually uses. */
      var v = Math.max(1, Math.min(100, Number(rate.value) || 30)) / 100;
      return 2 + 218 * v * v;
    }
    function crawlSet(on) {
      crawl = !!on;
      run.textContent = crawl ? '⏸' : '▶';
      run.classList.toggle('on', crawl);
      tools.classList.toggle('on', crawl);
      if (crawl) {
        follow = false;             /* the two cannot both drive */
        var chip = el('spNow');
        if (chip) chip.classList.add('adrift');
        crawlLast = 0;
        crawlOwed = 0;
        requestAnimationFrame(crawlStep);
      }
    }
    crawlStop = function () { crawlSet(false); };
    function crawlStep(ts) {
      if (!crawl) return;
      var box = el('spScript');
      if (!box) { crawl = false; return; }
      if (crawlLast) {
        crawlOwed += crawlRate() * ((ts - crawlLast) / 1000);
        var whole = Math.floor(crawlOwed);
        if (whole >= 1) {
          crawlOwed -= whole;
          selfScrollUntil = Date.now() + 400;   /* our own scroll (#the guard) */
          box.scrollTop += whole;
          if (box.scrollTop + box.clientHeight >= box.scrollHeight - 2) {
            crawlSet(false);                    /* the end of the script */
          }
        }
      }
      crawlLast = ts;
      if (crawl) requestAnimationFrame(crawlStep);
    }
    run.addEventListener('click', function (ev) {
      ev.stopPropagation();                     /* not a pane tap */
      crawlSet(!crawl);
    });
    rate.addEventListener('click', function (ev) { ev.stopPropagation(); });
    rate.addEventListener('input', function () {
      if (crawl) { crawlLast = 0; }             /* take the new rate now */
    });

    now.addEventListener('click', function () {
      itineraryOpen();
    });

    var detail = make('div', 'sp-detail');
    detail.id = 'spDetail';
    detail.hidden = true;
    right.appendChild(detail);

    var review = make('div', 'sp-rejection-detail');
    review.id = 'spRejectionDetail';
    review.hidden = true;
    review.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { event.preventDefault(); rejectionClose(); }
    });
    right.appendChild(review);

    host.appendChild(left);
    host.appendChild(right);
  }

  function mount(node) {
    /* [#1189] the recorder samples from tick(), after the marks are placed,
       so highlight and active are read in the same breath. */
    if (mounted) return Promise.resolve(true);
    build(node);
    retryReports();
    wirePlayer();
    mounted = true;
    rejectionLoad(true);
    foldLoad();                                              /* #1294 */
    if (!scopeFrame) paintScope();                           /* #1298 */

    var feed = root.PineStationFeed;
    if (feed && typeof feed.subscribe === 'function') {
      var paintedStation = null;
      var onFeed = function (payload) {
        var state = (payload && payload.station) || payload || {};
        var wasAt = liveStream && liveStream.at;
        liveStream = state.stream_now || null;
        if (!liveStream || liveStream.at !== wasAt) lastOffMs = 0;
        /* payload.now is interpolated from stream_now every 250 ms. Reading
           only the four-second station snapshot made both the highlight and
           this strip lag behind the audio by several lines. */
        speakingNow = (payload && payload.now) || state.speaking_now || null;
        flow = state.dialogue_flow || null;
        /* talk_next_in rides at the top of the payload, not inside
           dialogue_flow; fold it in so status() has one place to read. */
        if (flow && typeof state.talk_next_in === 'number') {
          flow.talk_next_in = state.talk_next_in;
        }
        stationPaused = !!state.paused;
        /* #1336: THE COMMITTED SEQUENCE. `admission` is the playout
           controller's own record of what it admitted, in the order it
           admitted it. Absent on a station that has not been patched yet,
           in which case admitMap.ok stays false and every road below
           falls back exactly as before. */
        admitMap = PineScriptCues.read(state.admission);
        /* Cancel the clock difference between this tablet and the station
           rather than assuming they agree; four seconds of drift would
           point the highlight at the wrong line. */
        if (state.server_ms) skewMs = Number(state.server_ms) - Date.now();
        correct();
        if (state !== paintedStation) {
          paintedStation = state;
          paintPlayer(state);
          paintFeed(state);
          loadScreenplay(false);
          loadPlan(false);                            /* #1289 */
        }
        tick();
      };
      stop = typeof feed.subscribeView === 'function'
        ? feed.subscribeView(host, onFeed) : feed.subscribe(onFeed);
    } else {
      loadScreenplay(true);
    }
    if (root.PineConsoleLine) root.PineConsoleLine.start();
    /* #1276: the read the operator is actually waiting on when they
       switch to this view. Forced, so it cannot be answered out of a
       twenty-second cache that predates the line now sounding. */
    loadScreenplay(true);
    loadPlan(true);                                   /* #1289 */
    if (!beat) beat = setInterval(tick, 1000);
    return Promise.resolve(true);
  }

  root.PineScriptPage = {
    mount: mount,
    /* [#1219] the timeline arithmetic, pure, plus what the strip reads now. */
    timeline: {model: timelineModel, rowsOf: timelineRows,
      interjects: timelineInterjects, source: timelineSource, read: timelineRead},
    /* The cue-map arithmetic, exported for
       tests/test_script_admission_view_2026_09_15.cjs. It is pure, so the
       test holds the real code rather than a copy of it. */
    cues: PineScriptCues,
    view: {screenplayOrder: screenplayOrder, bankSlotFor: bankSlotFor,
      readinessOf: readinessOf, readinessQueue: readinessQueue,
      readinessWhen: readinessWhen, readinessBankDetail: readinessBankDetail,
      readinessCardCoverage: readinessCardCoverage,
      paintReadinessDetail: paintReadinessDetail,
      liveScriptEvents: liveScriptEvents, feedScriptEvents: feedScriptEvents,
      liveCueWindow: liveCueWindow, turnEditBody: turnEditBody,
      itinConversationTurns: itinConversationTurns,
      itinConversationSections: itinConversationSections,
      itinBanked: itinBanked, itinAired: itinAired,
      folderRatioControls: folderRatioControls, folderH3Controls: folderH3Controls,
      folderSample: folderSample,
      bankSlotText: bankSlotText, planReviewLabel: planReviewLabel,
      rejectionLabel: rejectionLabel, rejectionGlyph: rejectionGlyph,
      rejectionPageItems: rejectionPageItems, rejectionListUrl: rejectionListUrl,
      rejectionBody: rejectionBody, rejectionEvidence: rejectionEvidence,
      rejectionPolicyBody: rejectionPolicyBody, rejectionDirectorBody: rejectionDirectorBody,
      rejectionAppendWords: rejectionAppendWords,
      rejectionTintSummary: rejectionTintSummary, rejectionProfileView: rejectionProfileView,
      scriptVisible: scriptVisible, playoutRead: playoutRead,
      playoutEvidence: playoutEvidence, paintSaying: paintSaying,
      sayingFallbackMark: sayingFallbackMark, placeMarks: placeMarks,
      contentGateBody: contentGateBody, contentGateEffective: contentGateEffective},
    /* #1168: the segment menu's own roads, exported the same way and
       for the same reason - a stub-DOM smoke test can then hold the
       REAL hold, the real three windows and the real sidebar rather
       than a copy of them that drifts. */
    segments: {
      identity: segIdentity,
      open: segMenuOpen,
      close: segMenuClose,
      inspect: segInspectOpen,
      report: segReportOpen,
      prompt: segPromptOpen,
      reason: segReportReason,
      steps: segFlowSteps,
      flow: segFlowPaint,
      seat: segSeatLook,
      /* [#1238] the taps, and the itinerary a tap on the
         script's name opens. */
      line: segLineCard,
      wire: segLineWire,
      tap: segFlowTap,
      reveal: segReveal,
      detail: segDetailOpen,
      replay: segLineReplay,
      itinerary: itineraryOpen,
      itinRow: itinRow,
      block: scriptBlock,
      download: segExportRun                          /* [#1220] */
    },
    /* [#1189] the resolver and the mark placement, exported for
       tests/test_script_view_evidence_2026_09_21.cjs - the real code,
       not a copy. */
    resolver: PineScriptResolver,
    marks: {place: placeMarks, keepLitInView: keepLitInView, stitch: stitchScript,
            anchor: scriptAnchor, restore: scriptRestore, nodes: scriptNodes,
            lines: lineNodes,
            follow: resumeAirFollow,
            decision: function () { return lastDecision; },
             reset: function () { lastDecision = null; airLast = null; lastGood = null;
                                  resolverRing.length = 0; nowLineId = ''; dressed = Object.create(null); },
             active: activeRow, playoutRead: playoutRead},
    folds: {bind: bindScriptOrder, apply: segApply, toggle: segToggle,
            jump: jumpToLine, reveal: revealLine, count: segCount},
    feedCrawl: {dress: feedCrawlDress, row: feedDress, measure: feedCrawlMeasure,
                start: feedCrawlStart, stop: feedCrawlStop},
    isMounted: function () { return mounted; },
    close: function () {
      rejectionClose();
      rejectionItems = [];
      rejectionFirstPage = [];
      rejectionCursor = null;
      rejectionHasMore = true;
      rejectionHeadAt = 0;
      rejectionLastStep = 0;
      rejectionPageRetryAt = 0;
      rejectionLoadEpoch += 1;
      rejectionLoading = false;
      mounted = false;
      folderClose();                                  /* 2026-09-14 */
      reasonClose();
      inboxClose();
      headerClose();                                  /* #1164 */
      segMenuClose();                                 /* #1168 */
      segInspectClose();
      segReportClose();
      segPromptClose();
      itineraryClose();                               /* [#1235] */
      feedCrawlStop();
      if (stop) stop();
      stop = null;
      if (beat) clearInterval(beat);
      beat = 0;
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineScriptPage;
})(typeof window !== 'undefined' ? window : globalThis);
