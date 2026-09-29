"""[no-repeat-24h] air_norepeat.Book: the day's memory of what went out.

Pure (no app): fingerprints that a new id cannot escape, a turn aired in chunks
meeting its whole self, the window, persistence across a restart, the first
seed from the ledgers, and refusals that are recorded, never silent."""
import json
import tempfile
import unittest
from pathlib import Path

import air_norepeat as nr


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def book(tmp, clock=None, **kw):
    return nr.Book(Path(tmp) / "book.json", Path(tmp) / "refusals.jsonl", clock=clock or Clock(), **kw)


class Fingerprints(unittest.TestCase):
    def test_new_id_same_words_is_the_same_key(self):
        a = nr.line_key("Whenever the Italians are on television.")
        b = nr.line_key("whenever the italians are on TELEVISION")
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_short_glue_is_not_keyed(self):
        self.assertEqual(nr.line_key("Yeah."), "")
        self.assertEqual(nr.line_key("Holy lord son."), "")        # 3 words < MIN_WORDS 4
        self.assertTrue(nr.line_key("Are you sure about that?"))

    def test_sentence_keys(self):
        ks = nr.sentence_keys("It is beside the point, honestly. It's just noise trying to get in here! Yeah.")
        self.assertEqual(len(ks), 2)


class TheBook(unittest.TestCase):
    def test_a_line_heard_is_refused_under_a_new_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = book(tmp)
            b.note_text("I just don't see how that relates to the actual content we are dealing with.",
                        road="banter", ref="line-1")
            self.assertTrue(b.used_text("I just don't see how that relates to the actual content we are dealing with"))
            self.assertFalse(b.used_text("A completely different line that nobody has said at all today."))

    def test_a_turn_heard_in_chunks_is_a_repeat_whole_and_a_chunk_of_a_heard_turn_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = book(tmp)
            b.note_text("That sounds like some deeply irrelevant historical noise.")     # chunk 1 on air
            b.note_text("I just don't see how that relates to the content.")            # chunk 2 on air
            turn = ("That sounds like some deeply irrelevant historical noise. "
                    "I just don't see how that relates to the content.")
            self.assertTrue(b.used_text(turn))                     # every sentence heard -> a replay
            fresh = turn + " And here is a brand new thought about the raccoon van."
            self.assertFalse(b.used_text(fresh))                   # one new sentence: not a repeat of a line
            b2 = book(tmp)
            b2.note_text(turn)
            self.assertTrue(b2.used_text("That sounds like some deeply irrelevant historical noise."))

    def test_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            b = book(tmp, clock=clock, window=86400)
            b.note("sfx", "abc123", "board")
            clock.t += 86399
            self.assertTrue(b.used("sfx", "abc123"))
            clock.t += 2
            self.assertFalse(b.used("sfx", "abc123"))

    def test_fresh_filters_before_the_roll(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = book(tmp)
            b.note("record", "t2", "rotation")
            self.assertEqual(b.fresh("record", ["t1", "t2", "t3"]), ["t1", "t3"])

    def test_it_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            b = book(tmp, clock=clock)
            b.note("record", "track-9", "rotation")
            b.note_text("The request line is ringing, you're live, go ahead.")
            self.assertTrue(b.save(force=True))
            again = book(tmp, clock=clock)
            self.assertTrue(again.used("record", "track-9"))
            self.assertTrue(again.used_text("the request line is ringing you're live go ahead"))

    def test_first_seed_from_the_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            now = 2_000_000.0
            (t / "air.jsonl").write_text("\n".join(json.dumps(r) for r in [
                {"id": "a", "air_at": now - 100, "aired": "stream", "kind": "call", "who": "dj",
                 "text": "No, bro, that isn't gonna work at all."},
                {"id": "b", "air_at": now - 90000, "aired": "stream", "kind": "call", "who": "dj",
                 "text": "An old line from yesterday that has served its day."},
                {"id": "c", "air_at": now - 50, "aired": "prepared", "kind": "call", "who": "dj",
                 "text": "A prepared line that never went out on the air."},
                {"id": "d", "air_at": now - 40, "aired": "stream", "kind": "sfx", "who": "board",
                 "text": "board"}]) + "\n")
            (t / "music.jsonl").write_text(json.dumps({"at": now - 10, "id": "rec-1"}) + "\n")
            (t / "sfx.jsonl").write_text(json.dumps({"ts": now - 5, "id": "clip-1", "who": "board"}) + "\n")
            clock = Clock(now)
            b = nr.Book(t / "book.json", t / "ref.jsonl", clock=clock,
                        seed=lambda: nr.seed_rows(t / "air.jsonl", t / "music.jsonl", t / "sfx.jsonl", now - 86400))
            self.assertTrue(b.used_text("No, bro, that isn't gonna work at all."))
            self.assertFalse(b.used_text("An old line from yesterday that has served its day."))
            self.assertFalse(b.used_text("A prepared line that never went out on the air."))
            self.assertTrue(b.used("record", "rec-1"))
            self.assertTrue(b.used("sfx", "clip-1"))

    def test_refusals_are_recorded_never_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = book(tmp)
            b.note_text("Regret is just another flavor of the same stale air.", road="banter")
            seen = b.text_seen("Regret is just another flavor of the same stale air.")
            row = b.refuse("line", seen["key"], "banter", text="Regret is just another flavor", stage="air")
            self.assertIn("min ago", row["why"])
            self.assertEqual(row["first_road"], "banter")
            on_disk = (Path(tmp) / "refusals.jsonl").read_text().splitlines()
            self.assertEqual(json.loads(on_disk[-1])["road"], "banter")
            self.assertEqual(b.state()["refusals_by_road"], {"line:banter": 1})


if __name__ == "__main__":
    unittest.main()
