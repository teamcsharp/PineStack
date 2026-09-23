"""Pure incident evidence tests: no app import, runtime I/O, audio or network."""
import json
import unittest

from script_diagnostics import (EVENT_LIMIT, ROW_LIMIT, TEXT_LIMIT, analyze_capture,
                                build_report, merge_views, normalize_view, render_report)


def event(identity='a', index=5, start=0, end=1, *, file='round.wav', source='bridge',
          first=1000, last=2000, samples=5, revision='doc-one'):
    return {'first_ms': first, 'last_ms': last, 'samples': samples,
            'highlight_id': identity, 'active_id': identity, 'element_index': index,
            'document_revision': revision, 'block': 12, 'ord': index,
            'audio': {'source': source, 'file': file,
                      'position_start_s': start, 'position_end_s': end}}


def view(events=None):
    return {'schema_version': 2, 'incident_id': 'incident-full-identity', 'phase': 'tap',
            'captured_at_ms': 3000, 'window': {'start_ms': 1000, 'end_ms': 3000},
            'events': events if events is not None else [event()],
            'rows': {name: {'id': name, 'text': 'unique words ' + name, 'media': 'round.wav',
                            'from_s': index * 2, 'until_s': index * 2 + 2}
                     for index, name in enumerate(('a', 'b', 'c'))},
            'snapshot': {'highlight_id': 'a', 'speaking_id': 'a', 'paused': False}}


class CaptureAnalysisTests(unittest.TestCase):
    def codes(self, capture):
        return {finding['code'] for finding in analyze_capture(capture)['findings']}

    def test_unchanged_coalesced_observations_are_not_line_jumps(self):
        capture = view([event(samples=240, first=1000, last=61000, end=59)])
        result = analyze_capture(capture)
        self.assertEqual(result['counts']['observations'], 240)
        self.assertEqual(result['counts']['events'], 1)
        self.assertEqual(result['findings'], [])

    def test_same_identity_dom_changes_are_classified_separately(self):
        capture = view([event(index=45), event(index=2, start=1, end=2, revision='doc-two'),
                        event(index=8, start=2, end=3, revision='doc-three')])
        result = analyze_capture(capture)
        self.assertEqual(self.codes(capture), {'same_line_dom_reindex'})
        self.assertEqual(result['counts']['same_line_dom_reindex'], 2)
        self.assertNotIn('highlight_identity_changes', result['counts'])

    def test_observed_same_file_backwards_line_and_position(self):
        capture = view([event('c', start=4, end=5), event('a', start=.2, end=1)])
        self.assertEqual(self.codes(capture),
                         {'same_file_line_regression', 'observed_position_regression'})

    def test_forward_missing_observation_is_not_declared_skipped_audio(self):
        result = analyze_capture(view([event('a'), event('c', start=4, end=5)]))
        finding = result['findings'][0]
        self.assertEqual(finding['code'], 'same_file_line_observation_gap')
        self.assertIn('do not prove skipped audio', finding['message'])

    def test_different_files_or_estimates_do_not_prove_sequence_regression(self):
        for second in (event('a', file='other.wav'), event('a', source='estimated'),
                       event('a', source='local')):
            with self.subTest(second=second):
                codes = self.codes(view([event('c', start=4, end=5), second]))
                self.assertNotIn('same_file_line_regression', codes)
                self.assertNotIn('observed_position_regression', codes)

    def test_missing_document_index_is_not_a_reindex(self):
        first = event()
        first.pop('element_index')
        self.assertNotIn('same_line_dom_reindex', self.codes(view([first, event()])))

    def test_changed_highlight_moving_back_is_a_display_observation_even_without_audio(self):
        capture = view([event('b', index=12, source='estimated'),
                        event('a', index=4, source='estimated')])
        result = analyze_capture(capture)
        self.assertEqual(self.codes(capture), {'highlight_document_regression'})
        self.assertEqual(result['counts']['highlight_identity_changes'], 1)
        self.assertIn('not audible order', result['findings'][0]['message'])

    def test_changed_document_mapping_does_not_assert_historical_cue_order(self):
        codes = self.codes(view([event('c', start=4, end=5),
                                event('a', start=5, end=6, revision='new-document')]))
        self.assertNotIn('same_file_line_regression', codes)

    def test_player_file_mismatch_is_cautious_and_preserves_exact_identity(self):
        identity = 'full-media-path-' + 'x' * 100 + '.wav'
        capture = view([event(file=identity)])
        normalized = normalize_view(capture)
        self.assertEqual(normalized['events'][0]['audio']['file'], identity)
        result = analyze_capture(capture)
        self.assertEqual(result['findings'][0]['code'], 'observed_file_mismatch')
        # [#1189] the finding names the CLASS of what was sounding - a line, a board
        # sting, an advert - because "path aliases require review" told the operator
        # nothing they could act on. Still cautious: it claims only that no captured
        # row named the file, never that the wrong thing was heard.
        self.assertIn('a line', result['findings'][0]['message'])
        self.assertIn('no captured row names', result['findings'][0]['message'])

    def test_published_prepared_do_not_become_audible_claims(self):
        capture = view([event(source='estimated')])
        capture['rows']['a']['aired'] = 'published'
        report = build_report(capture, {'feed': {'rows': [{'id': 'a', 'aired': 'prepared'}]}})
        self.assertFalse(report['analysis']['findings'])
        markdown = render_report(report, '/api/script-reports/one.json')
        self.assertIn('not audible-playback proof', markdown)
        self.assertNotIn('was heard', markdown)

    def test_server_and_client_clocks_are_retained_without_comparison(self):
        report = build_report(view(), {'observed_at_ms': 999000, 'speaking': {'id': 'b'}},
                              server_observed_at_ms=1000000)
        self.assertEqual(report['view']['captured_at_ms'], 3000)
        self.assertEqual(report['server']['observed_at_ms'], 999000)
        self.assertEqual(report['server_observed_at_ms'], 1000000)
        self.assertFalse(report['analysis']['findings'])

    def test_merge_preserves_tap_snapshot_and_interns_rows_once(self):
        tap, post = view(), view([event('b', start=2, end=3)])
        post.update(phase='post', captured_at_ms=13000)
        post['window'] = {'start_ms': 3000, 'end_ms': 13000}
        post['snapshot']['highlight_id'] = 'b'
        merged = merge_views(tap, post)
        self.assertEqual(len(merged['events']), 2)
        self.assertEqual(len(merged['rows']), 3)
        self.assertEqual(merged['snapshot']['highlight_id'], 'a')
        self.assertEqual(merged['post_snapshot']['highlight_id'], 'b')
        self.assertEqual(merged['captured_at_ms'], 3000)
        self.assertEqual(merged['post_captured_at_ms'], 13000)
        self.assertEqual(merged['window'], {'start_ms': 1000, 'end_ms': 13000})
        post['incident_id'] = 'wrong'
        with self.assertRaises(ValueError):
            merge_views(tap, post)

    def test_client_mapping_and_structured_error_evidence_survives(self):
        capture = view()
        capture['snapshot'].update(
            mapping_rows=['a', 'b'], mapping_rows_total=9, visibility='visible',
            layout={'live_segment': 'seg-live', 'highlighted_segment': 'seg-live',
                    'nodes_total': 400, 'nodes_hidden': 310,
                    'nodes_transitioning': 0, 'segments_folded': 18},
            errors=[{'at': 2000, 'kind': 'rejection', 'msg': 'capture failure'}],
            stream={'at': 1, 'length': 10, 'row_count': 3,
                    'rows': [{'id': 'a', 'from': 0, 'until': 2}]},
            viewport={'content_height_px': 1000})
        capture['events'][0]['audio_discontinuity'] = True
        capture['events'][0]['paused'] = True
        capture['events'][0].update(
            scroll_owner='restore', scroll_owner_at_ms=1999,
            live_segment='seg-live', highlighted_segment='seg-live',
            nodes_transitioning=3)
        capture['bounds'] = {'missing_rows': 1}
        result = normalize_view(capture)
        self.assertEqual(result['snapshot']['mapping_rows'], ['a', 'b'])
        self.assertEqual(result['snapshot']['errors'][0]['msg'], 'capture failure')
        self.assertEqual(result['snapshot']['stream']['rows'][0]['until'], 2)
        self.assertEqual(result['snapshot']['viewport']['content_height_px'], 1000)
        self.assertEqual(result['snapshot']['layout']['nodes_hidden'], 310)
        self.assertEqual(result['snapshot']['layout']['live_segment'], 'seg-live')
        self.assertTrue(result['events'][0]['audio_discontinuity'])
        self.assertTrue(result['events'][0]['paused'])
        self.assertEqual(result['events'][0]['scroll_owner'], 'restore')
        self.assertEqual(result['events'][0]['scroll_owner_at_ms'], 1999)
        self.assertEqual(result['events'][0]['live_segment'], 'seg-live')
        self.assertEqual(result['events'][0]['nodes_transitioning'], 3)
        self.assertEqual(result['bounds']['missing_rows'], 1)

    def test_context_elements_and_unavailable_player_telemetry_remain_explicit(self):
        capture = view()
        capture['rows']['element:scene-identity'] = {'id': 'element:scene-identity',
            'element_id': 'scene-identity', 'kind': 'heading', 'text': 'The next scene'}
        capture['snapshot'].update(recorder_version=2, capture_source='script-page',
            nearby=[{'id': 'element:scene-identity', 'element_id': 'scene-identity', 'index': 0}],
            audio={'source': 'bridge', 'player_state_available': False, 'volume': None,
                   'muted': None, 'ready_state': None, 'network_state': None, 'buffered_end_s': None})
        result = normalize_view(capture)
        self.assertEqual(result['snapshot']['recorder_version'], 2)
        self.assertEqual(result['snapshot']['capture_source'], 'script-page')
        self.assertIsNone(result['snapshot']['audio']['volume'])
        self.assertFalse(result['snapshot']['audio']['player_state_available'])
        self.assertEqual(result['snapshot']['nearby'][0]['id'], 'element:scene-identity')
        self.assertFalse(analyze_capture(capture)['findings'])

    def test_selected_mapping_context_is_not_misreported_as_dropped_evidence(self):
        capture = view()
        capture['snapshot'].update(context_index=47, context_source='viewport',
            mapping_rows=['a', 'b'], mapping_rows_total=100, mapping_rows_omitted=98,
            matching_file_rows_total=90)
        result = normalize_view(capture)
        self.assertEqual(result['snapshot']['context_index'], 47)
        self.assertEqual(result['snapshot']['context_source'], 'viewport')
        self.assertEqual(result['snapshot']['mapping_rows_omitted'], 98)
        self.assertEqual(result['snapshot']['matching_file_rows_total'], 90)
        self.assertEqual(result['bounds']['mapping_rows_omitted'], 0)
        self.assertFalse(any('Evidence is incomplete' in item
                             for item in analyze_capture(capture)['limitations']))

    def test_stamp_lead_requires_a_measurable_directional_lead(self):
        rows = [
            {'id': 'a', 'air_at': 10.0, 'heard_ack_at': 9.99},
            {'id': 'b', 'air_at': 20.0, 'heard_ack_at': 20.04},
        ]
        result = analyze_capture(view(), {'feed': {'rows': rows}})
        self.assertNotIn('stamp_lead_s', self.codes(view()))
        self.assertFalse(any(f['code'] == 'stamp_lead_s'
                             for f in result['findings']))

        rows.append({'id': 'c', 'air_at': 30.0, 'heard_ack_at': 30.2})
        result = analyze_capture(view(), {'feed': {'rows': rows}})
        lead = next(f for f in result['findings']
                    if f['code'] == 'stamp_lead_s')
        self.assertEqual(lead['count'], 1)
        self.assertIn('median of 0.2s', lead['message'])


class EvidenceBoundsTests(unittest.TestCase):
    def test_large_legacy_input_is_bounded_before_encoding_and_json_remains_valid(self):
        huge = 'x' * 100000
        raw = {'motion': [huge] * 5000, 'window': [huge] * 1000,
               'text': huge, 'payload': {'nested': huge}, 'nowLineId': 'legacy-full-id'}
        report = build_report(raw, {'unapproved': huge})
        encoded = json.dumps(report, allow_nan=False)
        decoded = json.loads(encoded)
        self.assertLess(len(encoded), 650000)
        self.assertEqual(decoded['view']['legacy']['omitted']['motion'], 5000 - EVENT_LIMIT)
        self.assertEqual(decoded['view']['legacy']['omitted']['motion_truncated'], EVENT_LIMIT)
        self.assertNotIn('payload', decoded['view'])
        self.assertNotIn('unapproved', decoded['server'])
        self.assertEqual(decoded['view']['snapshot']['highlight_id'], 'legacy-full-id')
        self.assertEqual(normalize_view(decoded['view'])['legacy'], decoded['view']['legacy'])

    def test_collection_omissions_and_nonfinite_values_are_explicit(self):
        raw = view([event()] * (EVENT_LIMIT + 30))
        raw['rows'] = {str(i): {'text': 'y' * 900, 'text_truncated': False} for i in range(ROW_LIMIT + 5)}
        raw['captured_at_ms'] = float('nan')
        raw['snapshot']['script_age_ms'] = float('inf')
        result = normalize_view(raw)
        self.assertEqual(result['bounds']['dropped_events'], 30)
        self.assertEqual(result['bounds']['dropped_rows'], 5)
        self.assertEqual(result['bounds']['truncated_texts'], ROW_LIMIT)
        self.assertTrue(result['rows']['0']['text_truncated'])
        self.assertEqual(len(result['rows']['0']['text']), TEXT_LIMIT)
        json.dumps(result, allow_nan=False)
        self.assertNotIn('captured_at_ms', result)
        self.assertEqual(normalize_view(result)['bounds'], result['bounds'])

    def test_markdown_contains_one_link_and_no_repeated_raw_evidence(self):
        report = build_report(view())
        report['metadata'] = {'reason': 'The mark moved backwards.', 'status': 'complete'}
        markdown = render_report(report, '/api/script-reports/incident.json')
        self.assertEqual(markdown.count('/api/script-reports/incident.json'), 1)
        self.assertNotIn('unique words', markdown)
        self.assertNotIn('```', markdown)
        self.assertIn('## What the station says happened', markdown)
        self.assertIn('The mark moved backwards.', markdown)
        encoded = json.dumps(report, allow_nan=False)
        self.assertEqual(encoded.count('unique words a'), 1)

    def test_server_context_retains_expected_bounded_observation_sizes(self):
        context = {'build_ms': 123, 'loop': {'recent': 'stalled'}, 'queue': [{'id': 'q'}] * 12,
                   'feed': {'rows': [{'id': str(i), 'aired': 'prepared'} for i in range(80)]},
                   'playback': {'events': [{'id': str(i)} for i in range(100)]},
                   'last_speech_receipt': {'at': 456}}
        report = build_report(view(), {'tap': context, 'post': context})
        self.assertEqual(len(report['server']['tap']['feed']['rows']), 80)
        self.assertEqual(len(report['server']['post']['playback']['events']), 100)
        self.assertEqual(report['server']['post']['build_ms'], 123)
        self.assertFalse(any(report['server_bounds'].values()))

    def test_render_links_screenshot_and_reports_its_distinct_time(self):
        report = build_report(view(), server_observed_at_ms=4000)
        report.update(images=['shot.png'], screenshot={'source': 'electron', 'at_ms': 4500})
        rendered = render_report(report, '/api/script-reports/one.json')
        self.assertIn('data/pine_uploads/shot.png', rendered)
        self.assertIn('captured at: 4500 ms', rendered)
        self.assertIn('Client tap timestamp: 3000 ms', rendered)
        self.assertIn('server observation timestamp: 4000 ms', rendered)


if __name__ == '__main__':
    unittest.main()
