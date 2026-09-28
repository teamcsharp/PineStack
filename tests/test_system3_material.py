"""[s3-material] The rows that name the manager's words, a gallery piece or
what people online are saying are eligible exactly when the station holds
the material, and the writer is handed it."""
import asyncio
import tempfile
import unittest
from unittest import mock

import system3


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 8, "names": {"A": "Host", "B": "Skip"},
            "subject": {"topic": "the raccoon took the van"}}
    base.update(over)
    return base


def plan(seed, cfg, **over):
    return system3.plan_scene(inputs(**over), cfg, system3.normalise_settings({"mode": "active", "test_seed": seed}))


def research_only(cfg):
    """Every RS draw lands in RS1 'argue', where only the online search can win."""
    for t in cfg["tables"]:
        if t["id"] == "RS1":
            for c in t["categories"]:
                if c["id"] == "argue":
                    for it in c["items"]:
                        it["weight"] = 1.0 if it["id"] == "online_search" else 0.0
    for st in cfg["structure"]["steps"]:
        for d in st.get("draws") or []:
            if d["family"] == "RS":
                d["category"] = "argue"
    return cfg


class EngineTests(unittest.TestCase):
    def test_a_row_names_the_material_it_needs(self):
        spec = {"requires": ["manager"], "text": "brings up the last thing the manager said from upstairs"}
        got = system3._direction_text(spec, {"material": {"manager": {"text": "Spin more records.", "label": "what he said"}}})
        self.assertIn('what he said: "Spin more records."', got)
        self.assertEqual(system3._direction_text(spec, {}), spec["text"])

    def test_research_reaches_the_writer_when_the_station_holds_it(self):
        cfg = research_only(system3.default_config())
        found = "People on the forum say the van was never locked."
        conv = plan("research", cfg, availability={"research": True},
                    material={"research": {"text": found, "label": "what people online are saying"}})
        rs = [e for e in conv["decision_events"] if e["family"] == "RS" and e.get("selected")]
        self.assertTrue(rs)
        self.assertTrue(all(e["selected"].get("id") == "online_search" for e in rs))
        self.assertTrue(all((e["selected"].get("material") or {}).get("kind") == "research" for e in rs))
        self.assertIn(found, system3.render_sheet(conv))

    def test_without_the_material_the_row_is_not_drawn(self):
        cfg = research_only(system3.default_config())
        conv = plan("no-research", cfg)
        self.assertFalse(any((e.get("selected") or {}).get("id") == "online_search"
                             for e in conv["decision_events"] if e["family"] == "RS"))
        self.assertNotIn("what people online are saying", system3.render_sheet(conv))


class RuntimeTests(unittest.TestCase):
    def test_the_host_material_reaches_the_round(self):
        import system3_runtime
        from test_system3_runtime import FakeStation, ctx, settle
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        station = FakeStation(tmp.name)
        asked = []
        station["system3_cts_material"] = lambda road, c, topic: (
            asked.append((road, topic)) or {"manager": {"text": "Talk less.", "label": "what he said", "ref": "m1"},
                                             "junk": {"no": "text"}})
        app = FastAPI()
        system3_runtime.install(app, station)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        rt = station["_system3"]()
        self.addCleanup(rt.store.close)
        self.addCleanup(settle)
        client.post("/api/system3/settings", json={"mode": "active", "test_seed": "mat"},
                    headers={"Authorization": "Bearer k"})
        h = asyncio.new_event_loop().run_until_complete(
            station["system3_direct_banter"](**ctx(bank=True, dj={"host_name": "Caine", "cohost_name": "Skip"})))
        self.assertTrue(asked)
        self.assertTrue(h.conv["inputs"]["availability"]["manager"])
        self.assertFalse(h.conv["inputs"]["availability"]["gallery"])
        self.assertEqual(sorted(h.conv["inputs"]["material"]), ["manager"])

    def test_a_host_without_the_hook_keeps_the_rows_off(self):
        import system3_runtime

        class Bare:
            def fail(self, *a):
                pass
        rt = system3_runtime.System3Runtime.__new__(system3_runtime.System3Runtime)
        rt.host = system3_runtime._Host({})
        rt.fail = lambda *a: None
        self.assertEqual(rt._cts_material("banter", {}, "x"), {})


class HostTests(unittest.TestCase):
    """app.py's system3_cts_material, with the station patched out."""

    @classmethod
    def setUpClass(cls):
        try:
            import app  # noqa: F401
        except Exception as exc:  # the station only imports inside its container
            raise unittest.SkipTest("app.py does not import here: %s" % exc)

    def test_the_manager_the_gallery_and_research(self):
        import time
        import app
        now = time.time()
        radio = {"chat": [{"who": "manager", "text": "Spin more records.", "air_at": now - 60, "id": "m1"},
                          {"who": "dj", "text": "later line", "air_at": now}],
                 "image_analysis_by_image": {"a.png": {"analysis": "a woman in a racing suit"},
                                             "b.png": {"analysis": ""}}}
        sent = []
        with mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "s3_choice", lambda key, opts, label="", tabled=True: opts[0]), \
                mock.patch.object(app, "settings_web_search", lambda: True), \
                mock.patch.object(app, "fire_and_forget", lambda coro: (sent.append(coro), coro.close())), \
                mock.patch.object(app, "_S3_RESEARCH", {}), mock.patch.object(app, "_S3_RESEARCH_BUSY", set()):
            got = app.system3_cts_material("banter", {}, "The raccoon took the van")
            self.assertEqual(got["manager"]["text"], "Spin more records.")
            self.assertIn("racing suit", got["gallery"]["text"])
            self.assertNotIn("research", got, "not searched yet")
            self.assertEqual(len(sent), 1, "searched in the background, once")
            app.system3_cts_material("banter", {}, "The raccoon took the van")
            self.assertEqual(len(sent), 1, "never twice while the search is running")
            app._S3_RESEARCH[app._s3_research_key("The raccoon took the van")] = {
                "at": time.time(), "text": "forum: it was never locked", "ref": "u"}
            got = app.system3_cts_material("banter", {}, "The raccoon took the van")
            self.assertIn("never locked", got["research"]["text"])

    def test_old_manager_words_are_not_news(self):
        import time
        import app
        radio = {"chat": [{"who": "manager", "text": "Old memo.", "air_at": time.time() - 5 * 3600}]}
        with mock.patch.object(app, "_RADIO", radio), mock.patch.object(app, "settings_web_search", lambda: False):
            self.assertNotIn("manager", app.system3_cts_material("banter", {}, ""))


if __name__ == "__main__":
    unittest.main()
