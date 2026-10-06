"""[book-opening] Book Time's opening may have both hosts welcome the listener (#1588, 2026-10-05).

The three scripts at the top are the station's own: openings written on 10-05 and
turned away by the count of the word "welcome". They are run through the real check.

Run from the repo root:  python3 -m unittest tests.test_book_time_opening_2026_10_05
"""
from __future__ import annotations

import asyncio
import copy
import sys
import tempfile
import unittest
from contextvars import ContextVar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the repo root, however this file is run

from fastapi import FastAPI  # noqa: E402

import dynamic_segments_runtime as dynamic  # noqa: E402
import segment_prompts  # noqa: E402

STATION = 'Chicken Tendo Little Pine Box FM Station'
TITLE = ('McCarthy and His Enemies - Record and Its Meaning -- William F Buckley Jr, L Brent Bozell, '
         'William Schlamm -- 1954')   # the catalogue title, as the library holds it
OLD_VERDICT = 'Opening must contain one actual title/station welcome and no closing'
TURNED_AWAY = [
    "A: Alright, welcome to Book Time on Chicken Tendo Little Pine Box FM Station. I'm Dill.\n"
    "B: And I'm Skip. Welcome listeners to this segment of Book Time.\n"
    "A: We're diving into McCarthy and His Enemies - Record and Its Meaning from chapter Blank Page today.\n"
    "B: A fascinating read, Dill. Let's see what these records have to say about the era.",
    "A: Welcome to Book Time on Chicken Tendo Little Pine Box FM Station. I am Dill.\n"
    "B: And I am Skip. Welcome listeners to Book Time on Chicken Tendo Little Pine Box FM Station.\n"
    "D: I am Billy Badass, and I am here because the cops are coming for me!\n"
    "A: We are diving into McCarthy and His Enemies - Record and Its Meaning, chapter Blank Page today.\n"
    "B: This section really opens up some dark corners of history, doesn't it?",
    "A: Welcome to Book Time on Chicken Tendo Little Pine Box FM Station. I am Dill.\n"
    "B: And I'm Skip. Welcome to Book Time on Chicken Tendo Little Pine Box FM Station.\n"
    "A: We are diving into McCarthy and His Enemies - Record and Its Meaning, looking at chapter Blank Page today.\n"
    "B: Indeed we are. We have some heavy material waiting for us in this section.",
]


class Ledger:
    def __init__(self):
        self.rows = []

    def note(self, gate, why='', passed=True, road='', text='', ref='', at=None, who=''):
        self.rows.append({'gate': gate, 'why': why, 'passed': passed, 'road': road, 'text': text, 'ref': ref})


class BookOpeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {name: getattr(segment_prompts, name) for name in
                    ('_HOST', '_PATH', '_BOOK', '_READ', '_MEMO', '_RIDES', '_RECENT')}
        self.addCleanup(lambda: [setattr(segment_prompts, name, value) for name, value in self.old.items()])
        segment_prompts._HOST = {}
        segment_prompts._PATH = Path(self.tmp.name) / 'segment_prompts.json'
        segment_prompts._BOOK = {'kinds': {}, 'uses': [], 'at': 0.0}
        segment_prompts._READ = [False]
        segment_prompts._MEMO, segment_prompts._RIDES, segment_prompts._RECENT = {}, {}, []
        self.rows = [{'id': 'ordinary-hour', 'kind': 'banter', 'minutes': 60, 'enabled': True}]
        self.ledger = Ledger()
        self.saves = []
        source = {'title': TITLE, 'book_id': 'mccarthy'}
        self.source = source

        class Resolver:
            async def resolve_async(self, *texts, **kw):
                return {'source': source, 'values': {'book': TITLE, 'bookchapter': 'Blank Page', 'booksegment': 'A section.',
                        'booktopic': 'the record', 'booksentence': 'The record speaks.', 'booksentences': 'The record speaks.',
                        'stationname': STATION}, 'rolls': []}

        class BookRuntime:
            weighted = object()
            preview_weighted = object()

        resolver = Resolver()
        self.g = {'DATA_DIR': Path(self.tmp.name), 'PRODUCED_ADS_DIR': Path(self.tmp.name) / 'ads',
                  '_LARDER': [], '_SHELF': {}, '_RADIO': {'sched_slot': {}, 'sched_pos': {}},
                  'schedule_read': lambda: {'presets': {'current': self.rows}},
                  'schedule_hour_slots': lambda store=None, key='', when=None: ('current', copy.deepcopy(self.rows), False),
                  'dialogue_row_ready': lambda kind, row: bool(row.get('made')),
                  'require_auth': lambda key: None, 'require_read_auth': lambda key: None,
                  'book_resolver': lambda: resolver, 'BOOK_PROMPT_RUNTIME': BookRuntime(),
                  'book_prompt_context': ContextVar('fake-book-context', default=None),
                  'banter_turns': lambda text: [(line[0], line[3:]) for line in text.splitlines() if line[1:3] == ': '],
                  'alt_brief_now': lambda: '', 'alt_brief_set': lambda value: None,
                  'segment_prepare_contract': lambda road: {'chain_order': len(self.g['_LARDER'])},
                  'pipeline_log': lambda *a, **kw: None, '_larder_save': lambda: self.saves.append(1),
                  'FLOW_LEDGER': self.ledger,
                  'dj_settings': lambda: {'host_name': 'Dill', 'cohost_name': 'Skip', 'station_name': STATION}}
        self.rt = dynamic.install(FastAPI(), self.g)

    def part(self, script, phase='opening', **more):
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100', 'book_phase': phase,
               'book_source': self.source, 'book_station': STATION, 'book_cast': {'A': 'Dill', 'B': 'Skip'},
               'book_roulette': {'source': self.source, 'values': {'booksentence': 'The record speaks.'}},
               'script': script, 'made': False}
        row.update(more)
        return row

    def turned_away(self, script, sid):
        return self.part(script, sid=sid, dynamic_superseded=True, dynamic_rejection_id=sid,
                         dynamic_phase_rejected={'why': OLD_VERDICT, 'phase': 'opening', 'at': 1.0},
                         handoff_unavailable={'why': 'Book Time phase rejected: ' + OLD_VERDICT, 'at': 1.0})

    def due(self):
        return {'kind': 'book_time', 'slot_id': 'book-15', 'due_at': 100,
                'slot': {'id': 'book-15', 'kind': 'book_time', 'minutes': 6.5},
                'owns_seconds': 390, 'road': 'banter', 'commit_id': 'book-15@100'}

    # ---- the rule
    def test_the_openings_the_station_wrote_on_10_05_are_openings(self):
        for script in TURNED_AWAY:
            self.assertGreaterEqual(script.lower().count('welcome'), 2, 'both hosts welcome the listener in it')
            self.assertEqual(self.rt.phase_error(self.part(script)), '', script[:70])

    def test_an_opening_still_needs_its_welcome_its_title_and_no_goodbye(self):
        rule = 'Opening must welcome listeners to Book Time by title and station, and must not close'
        no_welcome = "A: This is Book Time on %s. I'm Dill.\nB: And I'm Skip. Today, %s." % (STATION, TITLE)
        no_title = "A: Welcome to Book Time on %s. I'm Dill.\nB: And I'm Skip. Let us read." % STATION
        closes = TURNED_AWAY[0] + "\nA: Thanks for listening to Book Time on %s. Back to the music." % STATION
        for script in (no_welcome, no_title, closes):
            self.assertEqual(self.rt.phase_error(self.part(script)), rule, script[:60])

    def test_the_hosts_still_introduce_themselves_as_themselves(self):
        swapped = "A: Welcome to Book Time on %s. I'm Skip.\nB: And I'm Dill. We read %s." % (STATION, TITLE)
        self.assertIn('wrong host', self.rt.phase_error(self.part(swapped)))
        silent = "A: Welcome to Book Time on %s. I'm Dill.\nB: Welcome to Book Time. We read %s." % (STATION, TITLE)
        self.assertEqual(self.rt.phase_error(self.part(silent)), 'Both hosts must introduce themselves in their own roles: Skip')

    def test_one_welcome_per_episode_still_holds(self):
        first = self.part(TURNED_AWAY[0])
        self.assertEqual(self.rt.phase_error(self.part(TURNED_AWAY[1]), [first]), 'The episode already has its one welcome')
        talk = self.part("A: Welcome back to Book Time, everyone.\nB: The record speaks.", phase='discussion')
        self.assertEqual(self.rt.phase_error(talk, [first]), 'Discussion must not welcome listeners or close Book Time')
        plain = self.part("A: The record speaks, it says.\nB: And what does that tell us?", phase='discussion')
        self.assertEqual(self.rt.phase_error(plain, [first]), '')

    # ---- the second look
    def test_a_blocked_occurrence_carries_on_from_its_own_first_opening(self):
        shelf = [self.turned_away(script, 'opening-%d' % n) for n, script in enumerate(TURNED_AWAY)]
        self.g['_LARDER'].extend(shelf)
        self.assertEqual(self.rt.book_rows('book-15@100'), [], 'before: nothing on the shelf counts')
        asked = []

        async def banter(*a, **kw):
            asked.append(kw['angle'])
            kw['bank_to'].append({'script': "A: The record speaks, it says.\nB: And what does that tell us about the era?", 'made': False})

        self.g['dj_banter'] = banter
        self.g['larder_prepare'] = None
        asyncio.run(self.rt.prepare_book(self.due()))
        state = self.rt.last['book-15@100']
        self.assertNotEqual(state.get('state'), 'blocked', state)
        first, second, third = shelf
        self.assertNotIn('dynamic_phase_rejected', first); self.assertNotIn('dynamic_superseded', first)
        self.assertNotIn('handoff_unavailable', first)
        self.assertEqual(first['phase_readmitted']['was'], OLD_VERDICT)
        for other in (second, third):
            self.assertTrue(other['dynamic_superseded'], 'only one opening comes back')
            self.assertEqual(other['phase_repaired_by'], 'opening-0', 'the others are answered by it')
        self.assertEqual(self.rt.book_rows('book-15@100')[0], first)
        self.assertTrue(self.saves, 'and the shelf is saved')

    def test_the_next_part_asked_for_is_the_discussion_not_another_opening(self):
        first = self.turned_away(TURNED_AWAY[0], 'opening-0')
        first['made'] = True
        first['takes'] = [{'who': 'dj', 'seconds': 12}, {'who': 'cohost', 'seconds': 12}]
        self.g['_LARDER'].append(first)
        asked = []

        async def banter(*a, **kw):
            asked.append(kw['angle'])
            kw['bank_to'].append({'script': "A: The record speaks, it says.\nB: And what does that tell us about the era?", 'made': False})

        self.g['dj_banter'] = banter
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(len(asked), 1)
        self.assertIn('Continue the SAME title and passage', asked[0])
        self.assertNotIn('This is the OPENING only', asked[0])
        self.assertEqual([row['book_phase'] for row in self.rt.book_rows('book-15@100')], ['opening', 'discussion'])

    def test_a_part_that_is_still_wrong_stays_turned_away(self):
        swapped = "A: Welcome to Book Time on %s. I'm Skip.\nB: And I'm Dill. We read %s." % (STATION, TITLE)
        bad = self.turned_away(swapped, 'opening-bad')
        handed = self.turned_away(TURNED_AWAY[0], 'opening-aired'); handed['dynamic_handed_off'] = True
        answered = self.turned_away(TURNED_AWAY[1], 'opening-answered'); answered['phase_repaired_by'] = 'something-else'
        other_hour = self.turned_away(TURNED_AWAY[2], 'opening-other'); other_hour['dynamic_occurrence'] = 'book-45@200'
        self.g['_LARDER'].extend([bad, handed, answered, other_hour])
        rows = []
        self.assertEqual(self.rt.readmit_phases('book-15@100', rows), 0)
        self.assertEqual(rows, [])
        for row in (bad, handed, answered, other_hour):
            self.assertTrue(row['dynamic_superseded']); self.assertIn('dynamic_phase_rejected', row)

    # ---- the ledger
    def test_a_part_turned_away_is_in_the_ledger(self):
        row = self.part("A: Hello.\nB: Hello.", sid='opening-x')
        self.rt.reject_phase(row, 'Opening must welcome listeners to Book Time by title and station, and must not close')
        self.assertEqual(len(self.ledger.rows), 1)
        noted = self.ledger.rows[0]
        self.assertEqual(noted['gate'], 'round:book_phase'); self.assertIs(noted['passed'], False)
        self.assertTrue(noted['why'].startswith('opening: Opening must welcome')); self.assertEqual(noted['ref'], 'opening-x')
        self.assertIn('Hello.', noted['text'])

    def test_a_ledger_that_cannot_write_never_stops_the_episode(self):
        class Broken:
            def note(self, *a, **kw):
                raise RuntimeError('disk full')
        self.g['FLOW_LEDGER'] = Broken()
        row = self.part("A: Hello.\nB: Hello.")
        self.rt.reject_phase(row, 'wrong')
        self.assertTrue(row['dynamic_superseded'])
        self.g.pop('FLOW_LEDGER')
        self.rt.reject_phase(self.part("A: Hi.\nB: Hi."), 'wrong')       # and no ledger at all is fine


if __name__ == '__main__':
    unittest.main()
