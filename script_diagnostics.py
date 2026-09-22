"""Bounded, observation-only evidence for script-view incident reports.

This module never imports the station, reads runtime files, or controls audio.
Client clocks, server observations and player positions remain separate. A
highlight transition is evidence about the display, never proof of heard audio.
"""
from __future__ import annotations

from collections import Counter
from itertools import islice
import math


EVENT_LIMIT = 512
ROW_LIMIT = 768
TEXT_LIMIT = 600
ID_LIMIT = 1024


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _count(value):
    number = _number(value)
    return max(0, min(int(number), 10**12)) if number is not None else 0


def _fields(raw, strings=(), numbers=(), booleans=(), omissions=None):
    raw, out = _mapping(raw), {}
    for key in strings:
        value = raw.get(key)
        if isinstance(value, str):
            limit = TEXT_LIMIT if key in ('text', 'message', 'withdrawn_why') else ID_LIMIT
            out[key] = value[:limit]
            if len(value) > limit and omissions is not None:
                omissions['truncated_strings'] += 1
                if key == 'text':
                    omissions['truncated_texts'] += 1
                    out['text_truncated'] = True
    for key in numbers:
        value = _number(raw.get(key))
        if value is not None:
            out[key] = value
    for key in booleans:
        if isinstance(raw.get(key), bool):
            out[key] = bool(raw[key] or out.get(key)) if key == 'text_truncated' else raw[key]
    return out


def _audio(raw, omissions):
    out = _fields(raw, ('source', 'file'),
                  ('position_start_s', 'position_end_s', 'position_s', 'duration_s',
                   'observed_at_ms', 'age_ms', 'volume', 'ready_state', 'network_state',
                   'buffered_end_s'), ('paused', 'muted', 'player_state_available'), omissions)
    for key in ('volume', 'muted', 'ready_state', 'network_state', 'buffered_end_s'):
        if key in _mapping(raw) and raw[key] is None:
            out[key] = None
    if out.get('source') not in ('bridge', 'local', 'estimated', 'unavailable'):
        out['source'] = 'unavailable'
    return out


def _row(raw, omissions):
    return _fields(raw, ('id', 'element_id', 'kind', 'who', 'text', 'media', 'source',
                         'aired', 'sid', 'document_revision', 'sfx', 'url'),   # [#1189]
                   ('block', 'ord', 'from_s', 'until_s', 'from', 'until', 'document_index', 'index'),
                   ('text_truncated',), omissions)


def _snapshot(raw, omissions):
    raw = _mapping(raw)
    out = _fields(raw, ('highlight_id', 'active_id', 'document_revision', 'speaking_id',
                       'visibility', 'capture_source', 'context_source',
                       'expected_id', 'carried_id'),                     # [#1189]
                  ('script_age_ms', 'mapping_rows_total', 'mapping_rows_omitted',
                   'matching_file_rows_total', 'context_index', 'observed_head_age_ms',
                   'recorder_version'),
                  ('paused', 'follow'), omissions)
    out['audio'] = _audio(raw.get('audio'), omissions)
    # [#1189] how the mark was placed: the standing decision, the ring before it,
    # and the station's verdict - each bounded here, never re-derived.
    resolver = _resolver(raw.get('resolver'), omissions)
    if resolver is not None:
        out['resolver'] = resolver
    playout = _playout(raw.get('playout'))
    if playout is not None:
        out['playout'] = playout
    out['viewport'] = _fields(raw.get('viewport'), (),
                             ('scroll_top_px', 'height_px', 'width_px', 'lit_top_px',
                              'scroll_height_px', 'client_height_px', 'content_height_px'), ('in_view',))
    mapping_rows = raw.get('mapping_rows')
    if isinstance(mapping_rows, list):
        out['mapping_rows'] = [identity for identity in mapping_rows[:96]
                               if isinstance(identity, str) and len(identity) <= ID_LIMIT]
        omissions['mapping_rows_omitted'] += len(mapping_rows) - len(out['mapping_rows'])
    stream = _mapping(raw.get('stream'))
    out['stream'] = _fields(stream, ('file',), ('at', 'length', 'row_count'), omissions=omissions)
    for source, target, limit in ((stream, out['stream'], 32), (raw, out, 48)):
        key = 'rows' if source is stream else 'nearby'
        rows = source.get(key)
        if isinstance(rows, list):
            target[key] = [_row(r, omissions) for r in rows[:limit] if isinstance(r, dict)]
            omissions['snapshot_rows_omitted'] += max(0, len(rows) - limit)
    errors = raw.get('errors')
    if isinstance(errors, list):
        out['errors'] = [r[:300] if isinstance(r, str) else
                         _fields(r, ('kind', 'msg'), ('at',), omissions=omissions)
                         for r in errors[:12] if isinstance(r, (str, dict))]
        omissions['errors_omitted'] += max(0, len(errors) - 12)
        omissions['truncated_strings'] += sum(isinstance(r, str) and len(r) > 300 for r in errors[:12])
    return out


def _legacy(raw):
    """Keep legacy evidence bounded without guessing its positional CSV schema."""
    rows = {}
    for row in (raw.get('lit') or [])[:48] if isinstance(raw.get('lit'), list) else []:
        if isinstance(row, dict):
            identity = row.get('line') or row.get('id')
            if isinstance(identity, str):
                rows[identity] = {'id': identity, 'text': row.get('text', ''),
                                  'document_index': row.get('index')}
    converted = {'schema_version': 2, 'phase': 'tap', 'rows': rows,
                 'snapshot': {'highlight_id': raw.get('nowLineId') or raw.get('now_line_id'),
                              'script_age_ms': raw.get('fetchedAgeMs'),
                              'follow': raw.get('follow'),
                              'audio': {'source': 'estimated' if raw.get('headIsRead') is False else 'unavailable'}}}
    # Legacy rows stay only here, once. They are not treated as reliable v2 events.
    evidence, omitted = {}, {}
    for key, limit in (('motion', EVENT_LIMIT), ('window', 64)):
        values = raw.get(key)
        if isinstance(values, list):
            evidence[key] = [value[:ID_LIMIT] for value in values[-limit:] if isinstance(value, str)]
            omitted[key] = max(0, len(values) - limit)
            omitted[key + '_invalid'] = sum(not isinstance(value, str) for value in values[-limit:])
            omitted[key + '_truncated'] = sum(isinstance(value, str) and len(value) > ID_LIMIT for value in values[-limit:])
    return converted, {'version': 1, 'evidence': evidence, 'omitted': omitted}


def normalize_view(value):
    """Return a compact JSON-safe v2 view; every collection has a hard bound.

    Limits apply before encoding. The JSON document is never sliced. Unknown
    fields are excluded by schema, and bounded evidence omissions are counted.
    """
    raw = _mapping(value)
    legacy = None
    if raw.get('schema_version') != 2:
        raw, legacy = _legacy(raw)
    omissions = Counter()
    bounds = _mapping(raw.get('bounds'))
    for key in ('dropped_events', 'dropped_rows', 'truncated_texts', 'truncated_strings',
                'invalid_events', 'invalid_rows', 'snapshot_rows_omitted', 'errors_omitted',
                'mapping_rows_omitted', 'missing_rows',
                'resolver_ring_omitted', 'resolver_refusals_omitted'):   # [#1189]
        omissions[key] = _count(bounds.get(key))
    out = _fields(raw, ('phase', 'incident_id'), ('captured_at_ms', 'post_captured_at_ms'),
                  omissions=omissions)
    out['schema_version'] = 2
    out['window'] = _fields(raw.get('window'), (),
                            ('start_ms', 'end_ms', 'retention_ms', 'sample_ms', 'post_ms'))
    events = raw.get('events') if isinstance(raw.get('events'), list) else []
    omissions['dropped_events'] += max(0, len(events) - EVENT_LIMIT)
    out['events'] = []
    for raw_event in events[-EVENT_LIMIT:]:
        if not isinstance(raw_event, dict):
            omissions['invalid_events'] += 1
            continue
        event = _fields(raw_event, ('highlight_id', 'active_id', 'document_revision',
                                    'mark', 'road', 'sync', 'expected_id', 'carried_id'),   # [#1189]
                        ('first_ms', 'last_ms', 'samples', 'element_index', 'block', 'ord',
                         'scroll_top_px', 'lit_top_px'), ('follow', 'paused', 'audio_discontinuity'), omissions)
        event['audio'] = _audio(raw_event.get('audio'), omissions)
        out['events'].append(event)
    rows = _mapping(raw.get('rows'))
    out['rows'] = {}
    omissions['dropped_rows'] += max(0, len(rows) - ROW_LIMIT)
    for identity, row in islice(rows.items(), ROW_LIMIT):
        if not isinstance(identity, str) or len(identity) > ID_LIMIT or not isinstance(row, dict):
            omissions['invalid_rows'] += 1
            continue
        out['rows'][identity] = _row(row, omissions)
    out['snapshot'] = _snapshot(raw.get('snapshot'), omissions)
    if isinstance(raw.get('post_snapshot'), dict):
        out['post_snapshot'] = _snapshot(raw['post_snapshot'], omissions)
    out['bounds'] = {**dict(omissions), 'events_limit': EVENT_LIMIT,
                     'rows_limit': ROW_LIMIT, 'text_limit': TEXT_LIMIT}
    if legacy is not None:
        out['legacy'] = legacy
    elif isinstance(raw.get('legacy'), dict):
        # Only produced by this normalizer; re-bound it rather than trusting it.
        held = _mapping(raw['legacy'].get('evidence'))
        _, out['legacy'] = _legacy(held)
        prior_omissions = _mapping(raw['legacy'].get('omitted'))
        for key in out['legacy']['omitted']:
            out['legacy']['omitted'][key] += _count(prior_omissions.get(key))
    return out


# [#1189] --- the resolver's trail, bounded ---------------------------------
RESOLVER_RING_LIMIT = 40
RESOLVER_REFUSED_LIMIT = 6
_DECISION_STRINGS = ('source', 'file', 'key', 'mark', 'line_id', 'road', 'sync', 'why',
                     'occurrence_id', 'observed', 'expected_id', 'expected_via', 'carried_id')
_DECISION_NUMBERS = ('at_ms', 't', 'position', 'from', 'until', 'block', 'ord', 'carried_age_s')
_RING_STRINGS = ('mark', 'line_id', 'road', 'sync', 'source', 'key', 'why', 'refused_why',
                 'expected_id', 'carried_id', 'occurrence_id')
_RING_NUMBERS = ('at_ms', 't', 'refused')

_HEX32 = __import__('re').compile(r'^([0-9a-f]{32})(?:\.[a-z0-9]{1,4})?$')
_HEX16 = __import__('re').compile(r'^([0-9a-f]{16})(?:-[^/]*)?(?:\.[a-z0-9]{1,4})?$')


def media_ident(name):
    """The identity behind a clip's name - the same fold PineScriptCues.ident applies.

    `/media/<32hex>.wav?br=64`, `<32hex>.mp3` -> the 32-hex media key;
    `/sfx/<16hex>?t=..`, `<16hex>-v2-v20-<mtime>.wav`, `<16hex>-<mtime>-src.wav` -> the 16-hex
    sample id (sfx_levelled_name / _as_wav / sfx_video_levelled in app.py name the cache that way);
    anything else answers to its basename."""
    raw = str(name or '').split('?')[0].replace('\\', '/')
    base = raw.rsplit('/', 1)[-1].lower()
    if not base:
        return ''
    got = _HEX32.match(base)
    if got:
        return got.group(1)
    got = _HEX16.match(base)
    if got:
        return got.group(1)
    return base


def row_identities(row):
    out = []
    for key in ('media', 'clip_media', 'sfx', 'url', 'clip'):
        value = _mapping(row).get(key)
        if isinstance(value, str) and value:
            ident = media_ident(value)
            if ident and ident not in out:
                out.append(ident)
    return out


def _decision(raw, omissions):
    raw = _mapping(raw)
    if not raw:
        return None
    out = _fields(raw, _DECISION_STRINGS, _DECISION_NUMBERS, omissions=omissions)
    refused = raw.get('refused')
    if isinstance(refused, list):
        out['refused'] = [_fields(r, ('road', 'id', 'why'), omissions=omissions)
                          for r in refused[:RESOLVER_REFUSED_LIMIT] if isinstance(r, dict)]
        omissions['resolver_refusals_omitted'] += max(0, len(refused) - RESOLVER_REFUSED_LIMIT)
    return out


def _resolver(raw, omissions):
    raw = _mapping(raw)
    if not raw:
        return None
    out = {'decision': _decision(raw.get('decision'), omissions), 'ring': []}
    ring = raw.get('ring')
    if isinstance(ring, list):
        out['ring'] = [_fields(r, _RING_STRINGS, _RING_NUMBERS, omissions=omissions)
                       for r in ring[-RESOLVER_RING_LIMIT:] if isinstance(r, dict)]
        omissions['resolver_ring_omitted'] += max(0, len(ring) - RESOLVER_RING_LIMIT)
    return out


def _playout(raw):
    raw = _mapping(raw)
    if not raw:
        return None
    out = _fields(raw, ('verdict', 'occurrence_id', 'line_id', 'file'),
                  ('block', 'ord', 'offset_s', 'at_ms'), ('agrees',))
    if raw.get('agrees') is None:
        out['agrees'] = None
    return out


def resolver_summary(view):
    """Roads, marks and refusals across the window, and the decision that stood at the tap."""
    view = _mapping(view)
    events = view.get('events') if isinstance(view.get('events'), list) else []
    roads, marks, syncs = Counter(), Counter(), Counter()
    seen = False
    for event in events:
        event = _mapping(event)
        if event.get('mark') or event.get('road'):
            seen = True
            roads[str(event.get('road') or 'none')] += max(1, _count(event.get('samples')))
            marks[str(event.get('mark') or 'none')] += max(1, _count(event.get('samples')))
            syncs[str(event.get('sync') or '')] += max(1, _count(event.get('samples')))
    snapshot = _mapping(view.get('snapshot'))
    resolver = _mapping(snapshot.get('resolver'))
    decision = _mapping(resolver.get('decision'))
    refusals = []
    for entry in (resolver.get('ring') or [])[-RESOLVER_RING_LIMIT:]:
        entry = _mapping(entry)
        if _count(entry.get('refused')) and entry.get('refused_why'):
            refusals.append({'at_ms': entry.get('at_ms'), 'line_id': entry.get('line_id'),
                             'road': entry.get('road'), 'why': entry.get('refused_why')})
    out = {'available': bool(seen or decision), 'roads': dict(roads), 'marks': dict(marks),
           'syncs': dict(syncs), 'refusals': refusals[-8:],
           'decision': {k: decision.get(k) for k in ('mark', 'line_id', 'road', 'sync', 'why', 'source',
                                                     'file', 'expected_id', 'carried_id', 'observed')
                        if k in decision}}
    playout = _mapping(snapshot.get('playout'))
    if playout:
        out['playout'] = {k: playout.get(k) for k in ('verdict', 'line_id', 'block', 'ord', 'agrees')
                          if k in playout}
    return out
# [#1189] --- end ---------------------------------------------------------------


def merge_views(tap, post):
    """Join independent tap and post observations without repeating tap payload."""
    first, last = normalize_view(tap), normalize_view(post)
    if first.get('incident_id') and last.get('incident_id') != first['incident_id']:
        raise ValueError('Incident ID does not match the initial capture.')
    out = dict(first)
    out['phase'] = 'complete'
    out['post_captured_at_ms'] = last.get('captured_at_ms')
    out['events'] = first['events'] + last['events']
    out['rows'] = {**first['rows'], **last['rows']}
    out['post_snapshot'] = last['snapshot']
    out['window'] = {**first['window'], 'end_ms': last['window'].get('end_ms')}
    out['bounds'] = {key: _count(first['bounds'].get(key)) + _count(last['bounds'].get(key))
                     for key in first['bounds'] if key not in ('events_limit', 'rows_limit', 'text_limit')}
    return normalize_view(out)


# [#1189] --- the window's own facts -----------------------------------------
#
# Sixteen captures say "the script jumped" and the analyzer had nothing to
# say about WHY, because both reasons live outside the event ring:
#
#   * lines standing between the marked elements that were never put out -
#     rounds written, ledgered and then refused or still waiting. 90 of them
#     on the page in one hour of 2026-09-21. The mark steps over them,
#     correctly, and the step is what the operator sees as a jump.
#   * the stamp that PLACES a line on the page is `air_at`, frozen at the
#     render estimate when the row is published; `heard_ack_at` is the ear.
#     Measured 2026-09-21: median 62.6s apart, p90 116s. Every line heard
#     during that lead is drawn where the estimate put it, not where it
#     sounded.
#
# Both are read off the server context the store already attaches; nothing
# here fetches, and an absent field simply yields no finding.


def _span_ms(event):
    """How long one coalesced sample-run stood, in ms (0 for a single sample)."""
    first, last = _number(_mapping(event).get('first_ms')), _number(_mapping(event).get('last_ms'))
    if first is None or last is None:
        return 0.0
    return max(0.0, last - first)


def file_class(name):
    """What the player was sounding, in words an operator can act on.

    A welded round is a 32-hex media key (`/media/<32hex>.wav`, `<32hex>.mp3`);
    a board sting is a 16-hex sample id, whether it is served as `/sfx/<16hex>`
    or read back off the levelled cache as `<16hex>-v2-v20-<mtime>.wav`; an
    advert is an mp3 off `/ads-audio/`. The 16-hex test comes BEFORE the `.wav`
    test for exactly that reason."""
    raw = str(name or '').split('?')[0].replace('\\', '/')
    base = raw.rsplit('/', 1)[-1].lower()
    if not base:
        return 'nothing named'
    if _HEX32.match(base):
        return 'a line'
    if _HEX16.match(base):
        return 'a board sting'
    if '/ads-audio/' in raw.lower() or base.endswith('.mp3'):
        return 'an advert'
    if base.endswith('.wav'):
        return 'a line'
    return 'a clip'


def _server_feeds(server_context):
    """Every `feed.rows` list in the context - the tap's and the post's alike."""
    out = []
    top = _mapping(server_context)
    for holder in (top, _mapping(top.get('tap')), _mapping(top.get('post'))):
        rows = _mapping(holder.get('feed')).get('rows')
        if isinstance(rows, list):
            out.append(rows)
    return out


def window_facts(view, server_context=None):
    """Ghost rows inside the marked span, and the stamp lead over the ear.

    Pure: the view as normalized, the server context as bounded. `aired` is
    taken from the server row when it has one (it is the fresher truth) and
    from the captured row otherwise; the seat on the page can only come from
    the capture, so a ghost the client never captured is not counted - the
    finding is a floor, never an estimate."""
    view = _mapping(view)
    rows = view.get('rows') if isinstance(view.get('rows'), dict) else {}
    events = view.get('events') if isinstance(view.get('events'), list) else []
    aired_by_id, leads = {}, []
    for feed in _server_feeds(server_context):
        for raw in feed[:256]:
            raw = _mapping(raw)
            identity = str(raw.get('id') or '')
            if identity and isinstance(raw.get('aired'), str):
                aired_by_id[identity] = raw['aired']
            heard, stamped = _number(raw.get('heard_ack_at')), _number(raw.get('air_at'))
            if heard and stamped and heard > 0 and stamped > 0:
                leads.append(heard - stamped)
    seats = [_number(_mapping(e).get('element_index')) for e in events]
    seats = [s for s in seats if s is not None]
    ghosts, ghost_states = [], Counter()
    if seats:
        low, high = min(seats), max(seats)
        for identity, raw in rows.items():
            seat = _number(_mapping(raw).get('document_index'))
            if seat is None or not (low <= seat <= high):
                continue
            state = aired_by_id.get(identity) or str(_mapping(raw).get('aired') or '')
            if state in ('prepared', 'withdrawn'):
                ghosts.append({'id': identity, 'document_index': seat, 'aired': state,
                               'kind': str(_mapping(raw).get('kind') or '')})
                ghost_states[state] += 1
        ghosts.sort(key=lambda g: g['document_index'])
    leads.sort()
    median = leads[len(leads) // 2] if leads else 0.0
    return {'ghosts': ghosts[:32], 'ghost_states': ghost_states, 'leads': leads,
            'lead_median_s': round(median, 1), 'lead_max_s': round(leads[-1], 1) if leads else 0.0,
            'element_span': [min(seats), max(seats)] if seats else []}


def analyze_capture(view, server_context=None):
    """Describe display/player observations, keeping suspicion separate from proof."""
    view = normalize_view(view)
    events, rows = view['events'], view['rows']
    counts = Counter(events=len(events), observations=sum(max(1, _count(e.get('samples'))) for e in events))
    evidence = {}

    def finding(code, index):
        counts[code] += 1
        evidence.setdefault(code, [])
        if len(evidence[code]) < 8:
            evidence[code].append(index)

    # [#1189] WHAT KIND OF THING was sounding when nothing on the page named it.
    file_classes = Counter()
    previous = None
    for index, event in enumerate(events):
        audio = event['audio']
        observed = audio.get('source') in ('bridge', 'local')
        active = rows.get(event.get('active_id'), {})
        # [#1189] IDENTITIES, not spellings: /sfx/<id> against a levelled cache name or
        # a row's clip_media is one clip. Only a row that names something ELSE is a mismatch.
        names = row_identities(active)
        if observed and audio.get('file') and names and media_ident(audio['file']) not in names:
            finding('observed_file_mismatch', index)
            file_classes[file_class(audio['file'])] += 1        # [#1189]
        placed = event.get('mark')
        # [#1189] with the decision recorded, highlight and active are read in the same
        # breath; a difference is a placement fault. Without it (an older client) the two
        # were sampled by different timers and their disagreement is kept as before.
        #
        # AND IT MUST OUTLIVE ONE PAINT. Every one of the 30 occurrences across the
        # twenty captures (#1188-#1248) is a SINGLE 250ms sample: the recorder reads the
        # DOM mark before activeRow() runs and the class lands in the next tick, so one
        # sample of disagreement is the paint, not the placement. All thirty were printed
        # to the operator as faults. A real one stands for two samples or half a second.
        if (event.get('highlight_id') and event.get('active_id') and event['highlight_id'] != event['active_id']
                and (not placed or placed == 'air')
                and (_count(event.get('samples')) > 1 or _span_ms(event) >= 500)):
            finding('highlight_active_mismatch', index)
        if placed == 'air' and not observed:
            finding('mark_without_evidence', index)
        if previous:
            same_id = bool(event.get('highlight_id')) and event.get('highlight_id') == previous.get('highlight_id')
            if same_id:
                if (event.get('element_index') is not None and previous.get('element_index') is not None
                        and event['element_index'] != previous['element_index']):
                    finding('same_line_dom_reindex', index)
            elif event.get('highlight_id') and previous.get('highlight_id'):
                counts['highlight_identity_changes'] += 1
                if (event.get('document_revision')
                        and event.get('document_revision') == previous.get('document_revision')
                        and event.get('element_index') is not None
                        and previous.get('element_index') is not None
                        and event['element_index'] < previous['element_index']):
                    finding('highlight_document_regression', index)
            old_audio = previous['audio']
            same_file = (observed and old_audio.get('source') == audio.get('source')
                         and audio.get('file') and audio.get('file') == old_audio.get('file'))
            if same_file:
                before, after = old_audio.get('position_end_s'), audio.get('position_start_s')
                if before is not None and after is not None and after + .15 < before:
                    finding('observed_position_regression', index)
                old_row = rows.get(previous.get('active_id'), {})
                same_revision = (event.get('document_revision')
                                 and event.get('document_revision') == previous.get('document_revision'))
                if same_revision and event.get('active_id') and previous.get('active_id') and event['active_id'] != previous['active_id']:
                    start, old_start = active.get('from_s'), old_row.get('from_s')
                    if active.get('media') == audio['file'] == old_row.get('media') and start is not None and old_start is not None and start < old_start:
                        finding('same_file_line_regression', index)
                    # Only report an observed gap when another captured row lies
                    # between these cue windows. Coalesced samples are not jumps.
                    if active.get('media') == audio['file'] == old_row.get('media') and start is not None and old_start is not None and start > old_start:
                        if any(r.get('media') == audio['file'] and r.get('from_s') is not None and old_start < r['from_s'] < start for r in rows.values()):
                            finding('same_file_line_observation_gap', index)
        previous = event
    messages = {
        'same_line_dom_reindex': 'The same highlighted line changed document position; this is a display reindex, not a line transition.',
        'highlight_document_regression': 'The highlighted identity moved to an earlier element in the same document revision; this describes the view, not audible order.',
        'highlight_active_mismatch': 'The highlighted identity differs from the client active-line identity.',
        'observed_file_mismatch': 'The observed player file differs from the active row media identity; path aliases require review.',
        'observed_position_regression': 'The observed position moved backward within the same player file.',
        'same_file_line_regression': 'Active-line observations moved backward across cue windows within the same observed file.',
        'same_file_line_observation_gap': 'Active-line observations passed over a captured cue window; sampling gaps do not prove skipped audio.',
        'mark_without_evidence': 'The view marked a line ON AIR while its position was estimated, not read from a player; the mark must come from evidence.',   # [#1189]
    }
    # [#1189] SAY WHAT IT WAS. 'path aliases require review' over a board sting is not
    # something an operator can act on; the class of the file is.
    if file_classes:
        messages['observed_file_mismatch'] = (
            'The player was sounding %s that no captured row names (%s); the mark could not '
            'be placed on it.' % (
                ', '.join('%s x%d' % (name, n) for name, n in file_classes.most_common(4)),
                'a sting row carries sfx/url, not media' if 'a board sting' in file_classes
                else 'no row of that file was in the capture'))
    # [#1189] THE TWO FACTS THE OPERATOR'S QUESTION TURNS ON: lines standing on the page
    # that were never said, and how far ahead of the ear the stamps that place them are.
    facts = window_facts(view, server_context)
    if facts['ghosts']:
        counts['ghost_rows_in_window'] = len(facts['ghosts'])
        evidence.setdefault('ghost_rows_in_window', [g['document_index'] for g in facts['ghosts'][:8]])
        messages['ghost_rows_in_window'] = (
            '%d line(s) standing between the first and last marked element were never put out '
            '(%s); the mark steps over them and that step is the jump.' % (
                len(facts['ghosts']),
                ', '.join('%s x%d' % (state, n) for state, n in facts['ghost_states'].most_common(3))))
    if facts['leads']:
        counts['stamp_lead_s'] = len(facts['leads'])
        evidence.setdefault('stamp_lead_s', [])
        messages['stamp_lead_s'] = (
            'The stamp that places a line on the page ran ahead of the moment it was heard by '
            'a median of %.1fs (max %.1fs) over %d heard row(s) in this window.' % (
                facts['lead_median_s'], facts['lead_max_s'], len(facts['leads'])))
    findings = [{'code': code, 'count': counts[code], 'message': message,
                 'evidence': evidence.get(code, [])}
                for code, message in messages.items() if counts[code]]
    limits = ['Client timestamps and server observation timestamps are independent.',
              'Highlight changes, publication, prepared state and estimated clocks do not prove audible playback.',
              'Unchanged coalesced observations are represented by first_ms, last_ms and samples.',
              'Observed player progression does not verify speaker output or exclude gaps between samples.']
    if any(view['bounds'].get(key) for key in ('dropped_events', 'dropped_rows', 'invalid_events',
                                            'invalid_rows', 'missing_rows', 'mapping_rows_omitted')):
        limits.append('Evidence is incomplete; explicit omission counts are in view.bounds.')
    if view.get('legacy'):
        limits.append('Legacy positional motion rows are preserved separately and are not interpreted as v2 player observations.')
    # [#1189] the trail: which evidence placed the mark, how often, and what was refused.
    return {'counts': dict(counts), 'findings': findings, 'limitations': limits,
            'resolver': resolver_summary(view)}


def _bounded_context(value):
    """Bound an already allowlisted server context; never serialize runtime objects."""
    omissions = Counter()
    remaining = [8192]

    def visit(raw, depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 7:
            omissions['values_omitted'] += 1
            return None
        if raw is None or isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            omissions['strings_truncated'] += int(len(raw) > ID_LIMIT)
            return raw[:ID_LIMIT]
        if isinstance(raw, (int, float)):
            return _number(raw)
        if isinstance(raw, list):
            omissions['list_items_omitted'] += max(0, len(raw) - 128)
            return [visit(item, depth + 1) for item in raw[:128]]
        if isinstance(raw, dict):
            omissions['mapping_entries_omitted'] += max(0, len(raw) - 64)
            return {key[:80]: visit(item, depth + 1) for key, item in islice(raw.items(), 64)
                    if isinstance(key, str)}
        omissions['unsupported_values_omitted'] += 1
        return None

    top = _mapping(value)
    allowed = {'observed_at_ms', 'build_ms', 'speaking', 'stream', 'air', 'feed', 'playback',
               'queue', 'last_speech_receipt', 'loop', 'errors', 'tap', 'post'}
    out = visit({key: top[key] for key in allowed if key in top})
    return out, dict(omissions)


def build_report(view, server_context=None, *, server_observed_at_ms=None):
    normalized = normalize_view(view)
    server, omissions = _bounded_context(server_context)
    return {'schema_version': 2, 'view': normalized, 'server': server,
            'server_observed_at_ms': _number(server_observed_at_ms),
            'server_bounds': omissions,
            # [#1189] the analysis can see the server's own rows now: it needs their
            # `aired` and `heard_ack_at` to name ghosts and the stamp lead.
            'analysis': analyze_capture(normalized, server)}


def render_report(report, json_url):
    """Short human summary; the single JSON link owns all detailed evidence."""
    report = _mapping(report)
    view, analysis = _mapping(report.get('view')), _mapping(report.get('analysis'))
    metadata = _mapping(report.get('metadata'))
    status = metadata.get('status') or report.get('status') or view.get('phase', 'tap')
    reason = metadata.get('reason') or report.get('reason')
    lines = ['# Script view incident', '', 'Capture status: ' + str(status)[:80] + '.', '']
    if reason:
        lines += ['## Operator report', '', str(reason)[:1200], '']
    counts = _mapping(analysis.get('counts'))
    lines += ['## What the station says happened', '',
              '- Captured %d transition records representing %d client observations.' %
              (_count(counts.get('events')), _count(counts.get('observations')))]
    findings = analysis.get('findings') if isinstance(analysis.get('findings'), list) else []
    if findings:
        lines += ['- %s (%d).' % (str(f.get('message', ''))[:400], _count(f.get('count')))
                  for f in findings[:8] if isinstance(f, dict)]
    else:
        lines += ['- No classified anomaly in the captured observations; this does not establish correct or audible playback.']
    # [#1189] HOW THE MARK WAS PLACED - the resolver's own account, so the report explains itself.
    trail = _mapping(analysis.get('resolver'))
    if trail.get('available'):
        decision = _mapping(trail.get('decision'))
        lines += ['', '## How the mark was placed', '']
        if decision:
            lines.append('- At the tap the mark was %s (%s, %s%s): %s' % (
                'ON AIR on line ' + str(decision.get('line_id') or '')[:12] if decision.get('mark') == 'air' else 'not placed',
                str(decision.get('road') or 'none')[:40], str(decision.get('source') or '')[:20],
                (', file ' + str(decision.get('file') or '')[:48]) if decision.get('file') else '',
                str(decision.get('why') or '')[:200]))
            if decision.get('expected_id'):
                lines.append('- The station clock expected line %s; that guess is drawn as EXPECTED, never as ON AIR.' % str(decision['expected_id'])[:12])
            if decision.get('carried_id'):
                lines.append('- The last line heard, %s, was shown as LAST HEARD.' % str(decision['carried_id'])[:12])
        roads = _mapping(trail.get('roads'))
        if roads:
            lines.append('- Over the window the mark came from: ' + ', '.join(
                '%s x%d' % (str(k)[:24], _count(v)) for k, v in sorted(roads.items(), key=lambda kv: -_count(kv[1]))[:8]) + '.')
        for refusal in (trail.get('refusals') or [])[:4]:
            refusal = _mapping(refusal)
            lines.append('- Refused: line %s via %s - %s.' % (str(refusal.get('line_id') or '')[:12],
                str(refusal.get('road') or '')[:24], str(refusal.get('why') or '')[:120]))
        playout = _mapping(trail.get('playout'))
        if playout:
            lines.append('- The station\'s playout verdict: %s%s.' % (str(playout.get('verdict') or 'none')[:80],
                ' (the view disagreed)' if playout.get('agrees') is False else ''))
        lines.append('')
    lines += ['- Client and server times remain separate. Publication and estimated clocks are not audible-playback proof.', '',
              'Client tap timestamp: %s ms; client post timestamp: %s ms; server observation timestamp: %s ms.' %
              (view.get('captured_at_ms', 'unavailable'), view.get('post_captured_at_ms', 'pending'),
               report.get('server_observed_at_ms', 'unavailable')), '',
              '[Complete bounded evidence (JSON)](' + str(json_url).replace('\n', '').replace('\r', '') + ')', '']
    images = report.get('images') if isinstance(report.get('images'), list) else []
    if images:
        lines += ['## Screenshot', '']
        for value in images[:3]:
            if not isinstance(value, str) or not value:
                continue
            path = value if '/' in value else 'data/pine_uploads/' + value
            lines.append('![Captured script view](' + path.replace('\n', '').replace('\r', '') + ')')
        lines.append('')
    screenshot = _mapping(report.get('screenshot'))
    if screenshot:
        lines += ['Screenshot source: %s; requested at: %s ms; captured at: %s ms%s.' %
                  (str(screenshot.get('source') or screenshot.get('screenshot_source') or 'unavailable')[:100],
                   screenshot.get('requested_at_ms') or 'unavailable',
                   screenshot.get('at_ms') or screenshot.get('captured_at_ms') or screenshot.get('screenshot_at_ms') or 'unavailable',
                   '; ' + str(screenshot.get('error') or screenshot.get('screenshot_error'))[:300]
                   if screenshot.get('error') or screenshot.get('screenshot_error') else ''), '']
    return '\n'.join(lines)
