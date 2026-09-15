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
                         'aired', 'sid', 'document_revision'),
                   ('block', 'ord', 'from_s', 'until_s', 'from', 'until', 'document_index', 'index'),
                   ('text_truncated',), omissions)


def _snapshot(raw, omissions):
    raw = _mapping(raw)
    out = _fields(raw, ('highlight_id', 'active_id', 'document_revision', 'speaking_id',
                       'visibility', 'capture_source', 'context_source'),
                  ('script_age_ms', 'mapping_rows_total', 'mapping_rows_omitted',
                   'matching_file_rows_total', 'context_index', 'observed_head_age_ms',
                   'recorder_version'),
                  ('paused', 'follow'), omissions)
    out['audio'] = _audio(raw.get('audio'), omissions)
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
                'mapping_rows_omitted', 'missing_rows'):
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
        event = _fields(raw_event, ('highlight_id', 'active_id', 'document_revision'),
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

    previous = None
    for index, event in enumerate(events):
        audio = event['audio']
        observed = audio.get('source') in ('bridge', 'local')
        active = rows.get(event.get('active_id'), {})
        if observed and audio.get('file') and active.get('media') and audio['file'] != active['media']:
            finding('observed_file_mismatch', index)
        if event.get('highlight_id') and event.get('active_id') and event['highlight_id'] != event['active_id']:
            finding('highlight_active_mismatch', index)
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
    }
    findings = [{'code': code, 'count': counts[code], 'message': message, 'evidence': evidence[code]}
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
    return {'counts': dict(counts), 'findings': findings, 'limitations': limits}


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
            'server_bounds': omissions, 'analysis': analyze_capture(normalized)}


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
