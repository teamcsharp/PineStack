import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

from orchestrator_visuals import roulette_history, station_history, _CACHE


class VisualHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'history.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,family TEXT,at REAL,body BLOB)')
        _CACHE.clear()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, kind, family, event):
        self.db.execute('INSERT INTO events(kind,family,at,body) VALUES(?,?,?,?)',
                        (kind, family, 100.0, zlib.compress(json.dumps(event).encode())))
        self.db.commit()

    def expire(self):
        key = str(self.path.resolve())
        _, value, counters = _CACHE[key]
        _CACHE[key] = (-1000, value, counters)

    def test_all_retained_results_stage_dice_and_no_station_duplicates(self):
        for _ in range(9):
            self.add('decision', 'ES', {'selected': {'label': 'Joy'}, 'stages': [{'draw': {'dice': 1}}, {'draw': {'dice': 100}}], 'rng': {'dice': 100}})
        self.add('observation', 'STATION', {'key': 'caller', 'picked': 'Sam', 'dice': 20})
        self.add('observation', 'STATION', {'key': 'cut_in', 'hit': False, 'dice': 50})
        self.add('decision', 'STATION', {'selected': {'label': 'Duplicate'}, 'rng': {'dice': 20}})
        self.add('observation', 'COMMIT', {'selected': {'label': 'Not a roll'}, 'dice': 1})
        got = roulette_history(self.path)
        self.assertEqual(got['events'], 11)
        self.assertEqual(got['rolls'], 20)
        self.assertEqual(got['outcome_total'], 11)
        self.assertEqual(got['outcomes'][0], {'label': 'ES / Joy', 'value': 9})
        self.assertEqual(sum(r['value'] for r in got['dice']), 20)
        self.assertIn({'label': 'cut_in / miss', 'value': 1}, got['outcomes'])

    def test_cache_incremental_update_and_retention_recount(self):
        self.add('decision', 'ES', {'selected': {'label': 'Joy'}, 'rng': {'dice': 10}})
        self.assertEqual(roulette_history(self.path)['rolls'], 1)
        self.add('decision', 'RS', {'selected': {'label': 'Question'}, 'rng': {'dice': 30}})
        self.assertEqual(roulette_history(self.path)['rolls'], 1)
        self.expire()
        self.assertEqual(roulette_history(self.path)['rolls'], 2)
        self.db.execute('DELETE FROM events WHERE id=1'); self.db.commit(); self.expire()
        got = roulette_history(self.path)
        self.assertEqual(got['rolls'], 1)
        self.assertEqual(got['outcomes'][0]['label'], 'RS / Question')

    def test_retention_of_middle_events_recounts_and_deterministic_events_do_not_roll(self):
        for name in ['First', 'Middle', 'Last']:
            self.add('decision', 'ES', {'selected': {'label': name}, 'rng': {'dice': 11}})
        self.add('decision', 'ES', {'selected': {'label': 'Forced'}, 'rng': None})
        self.assertEqual(roulette_history(self.path)['rolls'], 3)
        self.db.execute('DELETE FROM events WHERE id=2'); self.db.commit(); self.expire()
        got = roulette_history(self.path)
        self.assertEqual(got['rolls'], 2)
        self.assertEqual(got['outcome_total'], 2)

    def test_dialogue_counts_are_retained_conversation_statuses_and_committed_lines(self):
        self.db.execute('CREATE TABLE conversations(status TEXT)')
        self.db.execute('CREATE TABLE lines(id TEXT)')
        self.db.executemany('INSERT INTO conversations VALUES(?)', [('committed',), ('planned',), ('committed',)])
        self.db.executemany('INSERT INTO lines VALUES(?)', [('one',), ('two',)])
        self.db.commit()
        dialogue = roulette_history(self.path)['dialogue']
        self.assertEqual(dialogue['conversations'], 3)
        self.assertEqual(dialogue['lines'], 2)
        self.assertEqual(dialogue['rows'][0], {'label': 'committed', 'value': 2})

    def test_empty_is_measured_missing_is_unmeasured(self):
        self.assertEqual(roulette_history(self.path)['rolls'], 0)
        self.assertFalse(station_history({})['readable'])
        runtime = SimpleNamespace(ready=True, store=SimpleNamespace(path=self.path), settings={'mode': 'shadow'})
        def hook(): pass
        hook.__self__ = runtime
        self.assertEqual(station_history({'system3_dice_live': hook})['mode'], 'shadow')

    def test_other_bucket_preserves_denominator_and_bad_events_are_reported(self):
        for i in range(12):
            self.add('decision', 'ES', {'selected': {'label': str(i)}, 'rng': {'dice': i + 1}})
        self.db.execute("INSERT INTO events(kind,family,at,body) VALUES('decision','ES',100,?)", (b'bad',)); self.db.commit()
        got = roulette_history(self.path)
        self.assertEqual(sum(r['value'] for r in got['outcomes']), 12)
        self.assertEqual(got['outcomes'][-1], {'label': 'Other results', 'value': 6})
        self.assertEqual(got['skipped'], 1)


if __name__ == '__main__':
    unittest.main()
