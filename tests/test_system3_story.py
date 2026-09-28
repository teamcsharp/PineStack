"""[s3-story] A story call-back (#1039) is planned from System 3's own call
structure: its protocol sheet is empty, so it used to be withheld unaired."""
import asyncio
import tempfile
import unittest

import system3
import system3_tables


def call_inputs(story):
    return {"road": "caller", "seats": ["A", "B", "C"], "turns": 10,
            "names": {"A": "Host", "B": "Skip", "C": "Tony"}, "subject": {"topic": "the van"},
            "call": {"first": "Tony", "name": "Drunk Tony", "story": story}}


def planned(story, cfg=None):
    cfg = cfg or system3.default_config()
    inp = call_inputs(story)
    conv = system3.new_conversation(inp, cfg, system3.normalise_settings({"mode": "active", "test_seed": "story"}),
                                    conversation_id="c-story")
    system3.plan_call(conv, cfg, inp)
    return conv


class EngineTests(unittest.TestCase):
    def test_a_call_back_says_where_the_story_left_off(self):
        conv = planned(True)
        by_leg = {t.get("leg"): t for t in conv["turns"]}
        self.assertIn("rung before", by_leg["introduce"]["protocol"])
        self.assertIn("left off", by_leg["detail_1"]["protocol"])
        self.assertIn("left off", system3.render_call_sheet(conv))

    def test_a_first_call_keeps_the_protocol(self):
        by_leg = {t.get("leg"): t for t in planned(False)["turns"]}
        self.assertIn("INTRODUCES THEMSELF", by_leg["introduce"]["protocol"])
        self.assertNotIn("left off", by_leg["detail_1"]["protocol"])

    def test_the_structure_may_carry_its_own_story_acts(self):
        cfg = system3.default_config()
        cfg.setdefault("structures", {})["caller"] = dict(system3_tables.default_structures()["caller"],
                                                          story_acts={"introduce": "{FIRST} is back, and says so."})
        by_leg = {t.get("leg"): t for t in planned(True, cfg)["turns"]}
        self.assertIn("TONY is back", by_leg["introduce"]["protocol"])

    def test_the_default_config_is_unchanged(self):
        self.assertEqual(system3_tables.STORY_ACTS.keys(), {"introduce", "detail_1"})


class RuntimeTests(unittest.TestCase):
    def test_a_story_call_back_is_directed_not_withheld(self):
        import system3_runtime
        from test_system3_runtime import FakeStation, ctx, settle
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        station = FakeStation(tmp.name)
        app = FastAPI()
        system3_runtime.install(app, station)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        rt = station["_system3"]()
        self.addCleanup(rt.store.close)
        self.addCleanup(settle)
        client.post("/api/system3/settings", json={"mode": "active", "test_seed": "story"},
                    headers={"Authorization": "Bearer k"})
        h = asyncio.new_event_loop().run_until_complete(station["system3_direct_banter"](**ctx(
            caller_name="Drunk Tony", seats=["A", "B", "C"], lines=10, road="caller",
            call_sheet="", call_meta={"story": {"id": "s1", "part": 2, "of": 3}, "topic": "the van"})))
        self.assertTrue(h is not None and h.active, "System 3 directs the call-back")
        self.assertIn("left off", h.sheet)


if __name__ == "__main__":
    unittest.main()
