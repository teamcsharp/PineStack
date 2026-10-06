# -*- coding: utf-8 -*-
"""[tabrelay] the station's side of the PineTab camera relay: the report door,
the relay setting, and the battery asked through the road in force.

Runs the shipped source of the new functions (extracted from app.py) against
stubs and a temporary data folder - never the live app, never /app/data."""
import ast
import asyncio
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

SRC = str(os.environ.get("TABRELAY_APP_SRC") or (Path(__file__).resolve().parents[1] / "app.py"))
S = io.open(SRC, encoding="utf-8").read()
TREE = ast.parse(S)
LINES = S.split("\n")


def fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            start = n.lineno - 1
            if n.decorator_list:
                start = n.decorator_list[0].lineno - 1
            return "\n".join(LINES[start:n.end_lineno])
    raise AssertionError("no function " + name)


def const(name):
    for n in TREE.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(getattr(t, "id", "") == name for t in targets):
                return "\n".join(LINES[n.lineno - 1:n.end_lineno])
    raise AssertionError("no constant " + name)


class _App:
    def get(self, *a, **k):
        return lambda f: f

    post = get


class _Unauthorized(Exception):
    pass


class _Req:
    def __init__(self, body, host="10.89.1.246", peer="10.89.1.154"):
        self._body = body
        self.url = type("U", (), {"hostname": host})()
        self.client = type("C", (), {"host": peer})()

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def build(tmp: Path):
    logs = []

    def require_auth(a):
        if a != "Bearer k":
            raise _Unauthorized()

    g: dict[str, Any] = {
        "Any": Any, "Path": Path, "json": json, "os": os, "re": re, "time": time,
        "asyncio": asyncio, "app": _App(), "Request": object, "Header": lambda default=None: default,
        "require_auth": require_auth, "require_read_auth": lambda a: None,
        "data_path": lambda *p: tmp.joinpath(*p),
        "PINELINK_STATE": tmp / "pinelink" / "state.json",
        "PINELINK_BATTERY_URL": "http://192.168.1.254/?custom=1&cmd=3019",
        "_PINELINK_ANNOUNCE": {"at": 0.0},
        "pipeline_log": lambda ch, t: logs.append((ch, t)),
    }
    names_c = ["PINELINK_RELAY_FILE", "PINELINK_RELAY_PREF_FILE", "PINELINK_RELAY_PREFS",
               "PINELINK_CAMERA_SSID", "PINELINK_CAMERA_PSK", "PINELINK_CAMERA_BSSID",
               "PINELINK_CAMERA_HOST", "PINELINK_RELAY_STALE_S", "PINELINK_RELAY_ALLOW",
               "_PINELINK_RELAY_IP"]
    names_f = ["pinelink_relay_ip", "pinelink_relay_pref", "pinelink_relay_clean",
               "pinelink_relay_reply", "pinelink_battery_url", "_pinelink_relay_write",
               "_pinelink_relay_state_raw", "pinelink_relay_view", "pinelink_relay_report_api",
               "pinelink_relay_api", "pinelink_relay_set_api"]
    code = "\n".join(const(c) for c in names_c) + "\n\n" + "\n\n".join(fn(f) for f in names_f)
    exec(compile(code, "tabrelay_app_extract", "exec"), g)
    g["_logs"] = logs
    return g


def run(co):
    return asyncio.run(co)


class TabrelayAppTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = Path(self.td.name)
        (self.tmp / "pinelink").mkdir()
        self.g = build(self.tmp)

    def tearDown(self):
        self.td.cleanup()

    def state(self, source=None, age=1.0):
        st = {"state": "live", "at": time.time() - age}
        if source is not None:
            st["source"] = source
        (self.tmp / "pinelink" / "state.json").write_text(json.dumps(st))

    def report(self, capable=True, **extra):
        body = {"v": 1, "capable": capable, "ip": "10.89.1.154",
                "link": {"state": "joined", "joined": True, "signal": 78, "why": ""},
                "relay": {"listening": True, "clients": 1}}
        body.update(extra)
        return run(self.g["pinelink_relay_report_api"](_Req(body), "Bearer k"))

    def test_default_denies_old_tablet_plan(self):
        pref_file = self.tmp / "pinelink_relay_pref.json"
        state = {"at": time.time(), "source": {"pref": "always", "use": "tablet", "want_tablet": True}}
        for raw in (None, "{bad json", "[]", "{}", '{"pref":"invalid"}'):
            if raw is None:
                pref_file.unlink(missing_ok=True)
            else:
                pref_file.write_text(raw)
            got = self.g["pinelink_relay_reply"](state, {"capable": True}, time.time(), ["10.89.1.246"])
            self.assertEqual(got["pref"], "never")
            self.assertFalse(got["want"])
            self.assertNotIn("psk", got)
            self.assertIn("DGX Spark", got["why"])

    def test_explicit_selection_allows_tablet_plan(self):
        state = {"at": time.time(), "source": {"pref": "never", "use": "tablet", "want_tablet": True}}
        for pref in ("auto", "always"):
            (self.tmp / "pinelink_relay_pref.json").write_text(json.dumps({"pref": pref}))
            got = self.g["pinelink_relay_reply"](state, {"capable": True}, time.time(), ["10.89.1.246"])
            self.assertEqual(got["pref"], pref)
            self.assertTrue(got["want"])

    # -- the door
    def test_report_needs_the_key(self):
        with self.assertRaises(_Unauthorized):
            run(self.g["pinelink_relay_report_api"](_Req({}), None))
        self.assertFalse((self.tmp / "pinelink_relay.json").exists())

    def test_report_is_written_with_announce_at(self):
        self.g["_PINELINK_ANNOUNCE"]["at"] = 1234.5
        self.state({"use": "dongle", "want_tablet": False, "why": "not wanted"})
        self.report()
        rep = json.loads((self.tmp / "pinelink_relay.json").read_text())
        self.assertEqual(rep["announce_at"], 1234.5)
        self.assertEqual(rep["ip"], "10.89.1.154")
        self.assertEqual(rep["peer"], "10.89.1.154")
        self.assertTrue(rep["capable"])
        self.assertTrue(rep["link"]["joined"])
        self.assertTrue(rep["relay"]["listening"])
        self.assertLess(abs(rep["at"] - time.time()), 5)

    def test_no_supervisor_source_is_not_wanted(self):
        self.state(None)
        got = self.report()
        self.assertFalse(got["want"])
        self.assertNotIn("psk", got)
        self.assertEqual(got["every_s"], 30)

    def test_stale_state_is_not_wanted(self):
        self.state({"use": "tablet", "want_tablet": True, "ip": "10.89.1.154"}, age=120)
        got = self.report()
        self.assertFalse(got["want"])
        self.assertEqual(got["use"], "dongle")
        self.assertIn("not running", got["why"])

    def test_incapable_tablet_is_never_wanted(self):
        """Local-only STA+STA off (today): the station never asks it to join."""
        self.state({"use": "dongle", "want_tablet": True})
        got = self.report(capable=False, link={"state": "unsupported", "why": "no local-only concurrency"})
        self.assertFalse(got["want"])
        self.assertNotIn("psk", got)
        self.assertIn("local-only", got["why"])

    def test_wanted_carries_the_network(self):
        self.state({"use": "dongle", "want_tablet": True, "why": "the PineTab is joining",
                    "mode": "udp", "rtsp_port": 8554, "http_port": 8580, "pref": "auto"})
        got = self.report()
        self.assertTrue(got["want"])
        self.assertEqual(got["ssid"], "H88_5c8e8bddfab1")
        self.assertEqual(got["psk"], "12345678")
        self.assertEqual(got["bssid"], "5c:8e:8b:dd:fa:b1")
        self.assertEqual(got["mode"], "udp")
        self.assertEqual(got["every_s"], 5)
        self.assertEqual(got["allow"][0], "10.89.1.246")
        self.assertEqual(len(got["allow"]), len(set(got["allow"])))

    def test_report_is_sanitised(self):
        self.state(None)
        run(self.g["pinelink_relay_report_api"](_Req({"ip": "10.0.0.999", "capable": 1,
            "link": {"signal": 900, "why": "x" * 999}, "relay": "junk"}), "Bearer k"))
        rep = json.loads((self.tmp / "pinelink_relay.json").read_text())
        self.assertEqual(rep["ip"], "")
        self.assertEqual(rep["link"]["signal"], 100)
        self.assertLessEqual(len(rep["link"]["why"]), 240)
        self.assertEqual(rep["relay"], {"listening": False})

    def test_bad_json_is_an_empty_report(self):
        self.state(None)
        got = run(self.g["pinelink_relay_report_api"](_Req(ValueError("x")), "Bearer k"))
        self.assertFalse(got["want"])

    # -- the setting
    def test_pref_default_and_set(self):
        view = run(self.g["pinelink_relay_api"](None))
        self.assertEqual(view["pref"], "never")
        self.assertIsNone(view["report"] or None)
        with self.assertRaises(_Unauthorized):
            run(self.g["pinelink_relay_set_api"](_Req({"pref": "never"}), None))
        got = run(self.g["pinelink_relay_set_api"](_Req({"pref": "never"}), "Bearer k"))
        self.assertEqual(got["pref"], "never")
        self.assertIn("dongle", got["say"])
        got = run(self.g["pinelink_relay_set_api"](_Req({"mode": "pass"}), "Bearer k"))
        self.assertEqual((got["pref"], got["mode"]), ("never", "pass"))   # merged
        bad = run(self.g["pinelink_relay_set_api"](_Req({"pref": "sometimes"}), "Bearer k"))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["pref"], "never")
        self.assertTrue(self.g["_logs"])

    def test_view_never_shows_the_password(self):
        self.state({"use": "tablet", "want_tablet": True, "ip": "10.89.1.154"})
        self.report()
        view = run(self.g["pinelink_relay_api"](None))
        self.assertNotIn("12345678", json.dumps(view))
        self.assertEqual(view["source"]["use"], "tablet")

    # -- the battery road
    def test_battery_url(self):
        u = self.g["pinelink_battery_url"]
        dongle = "http://192.168.1.254/?custom=1&cmd=3019"
        self.assertEqual(u(None), dongle)
        self.assertEqual(u({}), dongle)
        self.assertEqual(u({"source": {"use": "dongle", "ip": "10.89.1.154"}}), dongle)
        self.assertEqual(u({"source": {"use": "wait", "ip": "10.89.1.154"}}), dongle)
        self.assertEqual(u({"source": {"use": "tablet", "ip": ""}}), dongle)
        self.assertEqual(u({"source": {"use": "tablet", "ip": "10.89.1.154", "http_port": 8580}}),
                         "http://10.89.1.154:8580/?custom=1&cmd=3019")

    def test_battery_poll_is_wired_to_the_road(self):
        poll = fn("_pinelink_battery_poll")
        self.assertIn("url or PINELINK_BATTERY_URL", poll)
        self.assertIn("args=(pinelink_battery_url(link),)", fn("pinelink_battery"))


if __name__ == "__main__":
    unittest.main()
