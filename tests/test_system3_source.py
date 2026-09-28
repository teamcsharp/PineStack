"""[s3-source] The initiator node may pin the speakbox document a round opens
from; the station reads it only while System 3 is active on the road."""
import tempfile
import unittest

import system3_runtime


class SourceTests(unittest.TestCase):
    def boot(self, mode):
        from test_system3_runtime import FakeStation, settle
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
        auth = {"Authorization": "Bearer k"}
        client.post("/api/system3/settings", json={"mode": mode}, headers=auth)
        return station, rt, client, auth

    def test_the_first_steps_source_is_the_pin(self):
        station, rt, client, auth = self.boot("active")
        st = client.get("/api/system3/config").json()["config"]["structure"]
        steps = st["steps"]
        steps[0]["source"] = "43d.md"
        got = client.put("/api/system3/structure", json={"steps": steps}, headers=auth)
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(station["system3_pinned_source"]("banter"), "43d.md")

    def test_the_structure_may_carry_it_too(self):
        station, rt, client, auth = self.boot("active")
        st = client.get("/api/system3/config").json()["config"]["structure"]
        got = client.put("/api/system3/structure", json={"steps": st["steps"], "source": "aa.md"}, headers=auth)
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(station["system3_pinned_source"]("banter"), "aa.md")

    def test_nothing_is_pinned_unless_system3_is_active(self):
        station, rt, client, auth = self.boot("shadow")
        st = client.get("/api/system3/config").json()["config"]["structure"]
        st["steps"][0]["source"] = "43d.md"
        client.put("/api/system3/structure", json={"steps": st["steps"]}, headers=auth)
        self.assertEqual(station["system3_pinned_source"]("banter"), "")

    def test_nothing_pinned_by_default(self):
        station, rt, client, auth = self.boot("active")
        self.assertEqual(station["system3_pinned_source"]("banter"), "")


if __name__ == "__main__":
    unittest.main()
