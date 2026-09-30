"""[es-every-turn] a chunk with no voice of its own is heard in its seat's current
feeling - System 3's own state, the default ES tables' voice blocks."""
import threading
import types
import unittest

import system3
import system3_runtime

R = system3_runtime.System3Runtime


def es_pick(config):
    """The first ES category (and item) in the default tables that has a voice."""
    for t in config.get("tables") or []:
        if not str(t.get("id", "")).startswith("ES"):
            continue
        for c in t.get("categories") or []:
            for it in c.get("items") or [{}]:
                spec = {"table": t["id"], "category": c.get("id"), "id": it.get("id"), "label": it.get("label")}
                if system3.es_voice(config, spec):
                    return spec
    return None


def stub(config, conv, turn_index):
    s = types.SimpleNamespace(config=config, recent={"c1": conv}, lock=threading.Lock(), metrics={"perf_applied": 0},
                              store=types.SimpleNamespace(conversation=lambda cid: None))
    s._turn_of = lambda entry, text, who="": ("c1", turn_index)
    s._turn_of_loose = lambda entry, text, who="": None
    s.fail = lambda where, exc: (_ for _ in ()).throw(exc)
    s._seat_feel = types.MethodType(R._seat_feel, s)
    s._voice_miss = types.MethodType(R._voice_miss, s)
    return s


class EsEveryTurn(unittest.TestCase):
    def setUp(self):
        self.config = system3.default_config()
        self.spec = es_pick(self.config)
        self.assertIsNotNone(self.spec, "the default tables carry at least one ES voice")
        self.conv = {"participants": [{"actor_id": "A", "emotion": dict(self.spec, intensity=0.7, dims={"amusement": 0.4})}]}
        self.entry = {"system3": {"mode": "active", "conversation_id": "c1"}, "turn_dice": {}}

    def test_unmatched_chunk_takes_the_seats_feeling(self):
        s = stub(self.config, self.conv, None)
        got = R.perf_voice(s, self.entry, [], "words reworded on the way", "dj")
        want = system3.voice_intent(system3.es_voice(self.config, self.spec), 0.7)
        self.assertIsInstance(got, dict)
        self.assertEqual({k: got[k] for k in want}, want)
        self.assertEqual(got["row"]["source"], "the seat's current feeling")
        self.assertEqual(s.metrics.get("voice_miss_noturn"), 1)
        self.assertEqual(s.metrics.get("voice_seat"), 1)

    def test_turn_without_a_voice_takes_the_seats_feeling(self):
        s = stub(self.config, self.conv, 2)
        entry = dict(self.entry, turn_dice={"2": {"s3": {"perf": {"dims": {"amusement": 0.1}}}}})
        got = R.perf_voice(s, entry, [], "the planned words", "dj")
        self.assertIsInstance(got, dict)
        self.assertEqual(s.metrics.get("voice_miss_novoice"), 1)

    def test_a_turns_own_voice_still_wins(self):
        s = stub(self.config, self.conv, 1)
        own = {"tempo": 1.1, "pitch": 0.5}
        entry = dict(self.entry, turn_dice={"1": {"s3": {"perf": {"voice": own, "row": {"label": "x"}}}}})
        got = R.perf_voice(s, entry, [], "w", "dj")
        self.assertEqual(got["tempo"], 1.1)
        self.assertNotIn("voice_seat", s.metrics)

    def test_a_level_seat_stays_flat(self):
        conv = {"participants": [{"actor_id": "A", "emotion": {"table": "", "category": "", "label": "level"}}]}
        s = stub(self.config, conv, None)
        self.assertIsNone(R.perf_voice(s, self.entry, [], "w", "dj"))

    def test_perf_state_takes_the_seats_dims(self):
        s = stub(self.config, self.conv, None)
        got = R.perf_state(s, self.entry, [], "w", "dj")
        self.assertIsInstance(got, dict)
        self.assertAlmostEqual(got.get("amusement", 0.0), 0.4, places=3)


if __name__ == "__main__":
    unittest.main()
