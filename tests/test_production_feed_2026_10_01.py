"""[prod-feed] the pause, as a feed: System 3's rolls, the banking steps, the
emotion engine and the orchestrator's notes in one order, shaped for the roll stage."""
import unittest

import production_feed as pf


def decision(**over):
    ev = {"kind": "decision", "family": "TOPIC", "conversation_id": "c1", "turn_index": 2, "at": 100.0,
          "cursor": 7, "meta": {"road": "caller", "speaker": "caller"},
          "stages": [{"stage": "item", "total": 3.0, "of": 3, "selected": "b",
                      "draw": {"u": 0.41, "dice": 42, "sides": 100},
                      "candidates": [{"id": "a", "label": "the parking lot", "p": 0.5, "why": []},
                                     {"id": "b", "label": "the manager's memo", "p": 0.3, "why": ["fresh"]},
                                     {"id": "c", "label": "last night's news", "p": 0.2, "why": []}]}]}
    ev.update(over)
    return ev


class Rolls(unittest.TestCase):
    def test_a_decision_becomes_a_reel_with_its_winner_and_losers(self):
        [item] = pf.s3_items([decision()])
        self.assertEqual(item["type"], "roll")
        self.assertEqual(item["road"], "caller")
        row = item["rows"][0]
        self.assertEqual(row["main"]["dice"], 42)
        self.assertEqual(row["main"]["label"], "the manager's memo")
        self.assertEqual(row["main"]["opts"][row["main"]["hit"]], "the manager's memo")
        self.assertEqual(item["winner"]["label"], "the manager's memo")
        self.assertEqual([x["label"] for x in item["losers"]], ["the parking lot", "last night's news"])

    def test_the_winner_is_always_on_the_reel(self):
        cands = [{"id": str(i), "label": "line %d" % i, "p": 0.9 - i * 0.01} for i in range(30)]
        st = {"stage": "item", "candidates": cands, "selected": "29", "draw": 0.99, "total": 1.0, "of": 30}
        row = pf.stage_row("LINE", st)
        self.assertLessEqual(len(row["main"]["opts"]), pf.OPTS_SHOWN)
        self.assertEqual(row["main"]["opts"][row["main"]["hit"]], "line 29")
        self.assertEqual(row["main"]["of"], 30)

    def test_dice_doors(self):
        chance = {"family": "STATION", "kind": "observation", "key": "call.ending_success",
                  "label": "a call ends in success", "odds": 0.72, "u": 0.3, "dice": 31, "hit": True, "at": 5}
        pick = {"family": "STATION", "kind": "observation", "key": "ad.road", "label": "the ad's road",
                "candidates": ["sponsor", "gallery", "house"], "picked": "gallery", "index": 2, "of": 3,
                "u": 0.5, "dice": 51, "at": 6}
        roll = {"family": "STATION", "kind": "observation", "key": "x", "u": 0.25, "dice": 26, "at": 7}
        a, b, c = pf.s3_items([chance, pick, roll])
        self.assertEqual(a["rows"][0]["main"]["label"], "yes")
        self.assertIn("72%", a["title"])
        self.assertEqual(b["rows"][0]["main"]["label"], "gallery")
        self.assertEqual([x["label"] for x in b["losers"]], ["sponsor", "house"])
        self.assertEqual(c["rows"][0]["main"]["label"], "lands at 0.25")

    def test_observations_are_said(self):
        [g] = pf.s3_items([{"family": "GATE", "kind": "observation", "at": 3, "why": "a copied line was rewritten"}])
        self.assertEqual(g["type"], "gate")
        self.assertIn("rewritten", g["text"])


class Ring(unittest.TestCase):
    def test_notes_merge_in_time_order(self):
        pf.note("written", "manager", "A: a memo landed", label="a message from upstairs")
        rows = pf.ring_after(0)
        self.assertEqual(rows[-1]["stage"], "written")
        n = rows[-1]["n"]
        self.assertEqual(pf.ring_after(n), [])
        merged = pf.merge([{"at": 3, "x": 1}], [{"at": 1, "x": 2}], [{"at": 2, "x": 3}])
        self.assertEqual([r["x"] for r in merged], [2, 3, 1])

    def test_emotion_and_pipeline_since(self):
        tasks = [{"at": 10, "speaker": "dj", "text": "hi", "es": {"energy": 1.2}, "shaped_by_es": True},
                 {"at": 1, "speaker": "dj", "text": "old"}]
        self.assertEqual([t["text"] for t in pf.emotion_items(tasks, 5)], ["hi"])
        pipe = [{"ts": 9000, "kind": "lookahead", "text": "a round is READY"},
                {"ts": 9000, "kind": "chat", "text": "not ours"}, {"ts": 1000, "kind": "model", "text": "old"}]
        self.assertEqual([p["text"] for p in pf.pipeline_items(pipe, 5000)], ["a round is READY"])


class Route(unittest.TestCase):
    def test_the_route_is_installed(self):
        import app
        self.assertIn("/api/production/feed", {getattr(r, "path", "") for r in app.app.routes})


if __name__ == "__main__":
    unittest.main()
