import copy
import re
from pathlib import Path

import flow_chart
import system3
from test_system3_reply_roulette import EXTREME, scene


def test_flow_and_all_turn_roulette_cards_share_recorded_reply_decisions():
    conv, config = scene(opening=EXTREME)
    flow = flow_chart.build_flow(conv)
    nodes = {n['id']: n for n in flow['nodes']}
    for turn in conv['turns']:
        node = nodes['t:' + turn['turn_id']]
        assert node['reply_to'] == turn.get('reply_to')
        assert node['turn_credit'] == turn.get('turn_credit', 0)
        if turn.get('reply_to'):
            assert any(e['to'] == node['id'] and e['from'] == 't:' + turn['reply_to']['turn_id']
                       for e in flow['reply_edges'])
    graph_events = [e for e in conv['decision_events'] if e['family'] == 'GRAPH' and e.get('turn_id')]
    assert graph_events
    for event in graph_events:
        turn = next(t for t in conv['turns'] if t['turn_id'] == event['turn_id'])
        assert any(d['event_id'] == event['event_id'] for d in turn['decisions'])
        assert event['meta']['kind']
    report = flow_chart.report_text(flow)
    assert 'CAST REACTION ->' in report and '+1 turn restored' in report
    assert flow['counts']['cast_reactions'] == 2


def test_replanning_flow_hides_superseded_roulette_results():
    conv, config = scene()
    system3.observe(conv, 0, EXTREME)
    system3.replan(conv, config, 1, until=len(conv['turns']))
    flow = flow_chart.build_flow(conv)
    ids = {n['id'] for n in flow['nodes']}
    replaced = [e for e in conv['decision_events'] if e.get('meta', {}).get('superseded_by_revision')]
    assert replaced
    assert all('d:' + e['event_id'] not in ids for e in replaced)
    assert system3.replay(copy.deepcopy(conv), config)['ok']


def writer_helpers():
    # Read only the small writer functions, without starting the radio app.
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    constants = source[source.index('_BANTER_BEAT_ROW ='):source.index('def _sheet_speaks_direction')]
    helpers = source[source.index('def _beat_answers('):source.index('async def _s3_copy_gate(')]
    ns = {'re': re, 'Any': object}
    exec(compile(constants + helpers, 'writer-reply-helpers', 'exec'), ns)
    return ns


def test_writer_answers_nonadjacent_target_and_strips_machine_annotation():
    ns = writer_helpers()
    rows = ns['_banter_beat_plan']('1 A - opens\n2 B - answers\n3 D - answers\n4 B - Answer Host [reply-target=1]', 4, ['A', 'B', 'D'])
    assert rows[3]['reply_target'] == 1
    assert '[reply-target=' not in rows[3]['work']
    transcript = [('A', 'The transmitter is overheating.'), ('B', 'The headphones crackle.'), ('D', 'The mixer battery is empty.')]
    check = ns['_beat_sequence_answers']
    assert check(transcript[-1][1], rows[3:], [('B', 'Your transmitter needs a cooling fan.')], transcript)
    assert not check(transcript[-1][1], rows[3:], [('B', 'Replace that mixer battery.')], transcript)
