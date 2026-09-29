# -*- coding: utf-8 -*-
"""[airplayers] the receivers switch: a SET of receivers that sound the
station, persisted, and the heard receipts still flowing from the one that
is left audible.

Runs the shipped source of the new functions and the ones they lean on
(audio_owner, listener_roster, page_playback_ack, page_wedge_state) against
stubs, in the style of test_audio_owner_1185.py."""
import ast
import asyncio
import io
import os
import re
import sys
import time
import unittest
from pathlib import Path

_arg = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].endswith(".py") else None
SRC = str(os.environ.get("AIR_APP_SRC") or (_arg if _arg and _arg.is_file()
          else Path(__file__).resolve().parents[1] / "app.py"))
S = io.open(SRC, encoding="utf-8").read()
TREE = ast.parse(S)
LINES = S.split("\n")


def fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.name == name:
            start = n.lineno - 1
            if getattr(n, "decorator_list", None):
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


class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _Req:
    def __init__(self, body):
        self._b = body
        self.client = None
        self.headers = {}

    async def json(self):
        return dict(self._b)


def build():
    st = {"settings": {"terminals": {}}}
    routed = []
    ns = {"time": time, "re": re, "Any": object, "app": _App(),
          "Header": lambda default=None: default, "Request": object,
          "HTTPException": _HTTPException,
          "require_auth": lambda a: None, "require_read_auth": lambda a: None,
          "AUDIO_OWNER_LIFE": 90.0, "AUDIO_OWNER_QUICK": 12.0,
          "OWNER_DEAF_SECONDS": 75.0, "OWNER_DEAF_REST": 300.0,
          "_AUDIO_OWNER": {}, "_LISTENER_SEEN": {}, "_LISTENERS": {},
          "_OWNER_RUN": {"who": "", "since": 0.0}, "_OWNER_DEAF": {},
          "_PAGE_ACK_EVENTS": [], "_PAGE_DELIVERIES": {},
          "_TERMINALS_CACHE": {"at": 0.0, "rows": {}}, "TERMINALS_TTL": 0.0,
          "_RADIO": {"music_to": "here", "voice_to": "here",
                     "reply_to": "here", "voice_device": "nabu",
                     "box_talk": True},
          "_BOX_LAST_OK": [0.0],
          "_DIALOGUE_HEARD": [0.0], "_BANK_RETIMED": [0.0, 0.0],
          "_LISTENERS_SEEN": [0.0], "_STREAM_NOW": {},
          "PAGE_WEDGE_QUIET": 45.0, "PAGE_WEDGE_WAITING": 4,
          "radio_paused": lambda: False, "radio_paused_for": lambda: 0.0,
          "prepared_seconds": lambda: 0.0,
          "page_delivery_waits": lambda r: False,
          "dialogue_quiet_for": lambda: 0.0,
          "_stream_now_set": lambda *a, **k: None,
          "_sfx_cadence_pictures": lambda *a, **k: None,
          "talk_said_now": lambda *a, **k: None,
          "render_backlog_ack": lambda *a, **k: None,
          "_page_delivery_rows": lambda clip: [],
          "_ready_round_ack": lambda *a, **k: None,
          "page_recovery_read": lambda: [], "page_recovery_write": lambda r: None,
          "playout_tell": lambda *a, **k: None,
          "station_flow_event": lambda *a, **k: None,
          "pipeline_log": lambda *a, **k: None}
    receipts = []
    ns["_acknowledge_delivery_lines"] = (
        lambda did, clip, pos, interval: receipts.append(did) or True)

    def load_settings():
        return {k: (dict(v) if isinstance(v, dict) else v)
                for k, v in st["settings"].items()}

    def save_settings(data):
        # the real save runs validate_settings; the two keys this build owns
        data = dict(data)
        data["air_receivers"] = ns["validate_air_receivers"](
            data.get("air_receivers"))
        st["settings"] = data
        return data

    async def dj_output_api(request, authorization=None):
        body = await request.json()
        routed.append(body)
        for s in ("music", "voice", "reply"):
            if body.get(s):
                ns["_RADIO"][s + "_to"] = "box" if body[s] == "nabu" else body[s]
        if body.get("voice_device"):
            ns["_RADIO"]["voice_device"] = body["voice_device"]
        return {}

    ns.update(load_settings=load_settings, save_settings=save_settings,
              dj_output_api=dj_output_api)
    for c in ("LISTENER_WHAT", "AIR_PAGE_RECEIVERS", "AIR_SPEAKERS",
              "AIR_STREAMS", "AIR_RECEIVER_LABEL", "AIR_RECEIVER_WHAT",
              "AIR_STREAM_WORD", "_AIR_RECV_CACHE"):
        exec(const(c), ns)
    for f in ("terminal_rows", "terminal_for_listener", "_listener_live",
              "_listeners_live", "_listener_for_terminal", "_owner_deaf_key",
              "_owner_resting", "_owner_takes_nothing", "audio_owner",
              "listener_note", "listener_kind", "listener_device",
              "listener_name", "listener_roster", "validate_air_receivers",
              "air_receiver_for", "air_flags", "air_speakers", "_air_rid_of",
              "air_present", "air_effective", "air_hushed",
              "air_several_audible", "air_receivers_state", "_AirAsk",
              "air_speaker_route", "air_receivers_set_api",
              "page_playback_ack", "page_wedge_state"):
        exec(fn(f), ns)
    return ns, st, routed, receipts


KIOSK = "Mozilla/5.0 (Linux; Android 14) PineBoxKiosk/1.0"


def seat(ns, who, addr="", agent="", public=False, ago=1.0):
    now = time.time()
    ns["_LISTENER_SEEN"][who] = {"first": now - 600, "at": now - ago,
                                 "addr": addr, "agent": agent,
                                 "public": public}
    ns["_LISTENERS"][who] = now - ago


def house(ns, st, pinetab=True, desktop=False):
    """The live shape measured 2026-09-29: the tablet, the app (its shell and
    its panel webview) and one address-less web page."""
    st["settings"] = {"terminals": {
        "pinetab": {"name": "PineTab", "play": pinetab, "addr": "10.89.1.154",
                    "listener": "pb1d0amsvb", "fallback": False},
        "desktop": {"name": "This app", "play": desktop, "addr": "10.89.1.13",
                    "listener": "", "fallback": True}}}
    seat(ns, "pbnnmzpnrf", "10.89.1.154", KIOSK)
    seat(ns, "desktop-rvaf7exq", "10.89.1.13", "Electron")
    seat(ns, "pbkztc5rkx", "10.89.1.13", "Mozilla/5.0 (Windows NT 10.0)")
    seat(ns, "yzhfb4a8qbj")


def post(ns, body):
    return asyncio.run(ns["air_receivers_set_api"](_Req(body), "k"))


def row(state, rid):
    return next(r for r in state["receivers"] if r["id"] == rid)


class AirReceivers(unittest.TestCase):

    def test_each_surface_maps_to_its_receiver_and_off_means_hushed(self):
        ns, st, _, _ = build()
        house(ns, st)
        h = ns["air_hushed"]
        self.assertFalse(h("pbnnmzpnrf"))            # PineTab on
        self.assertTrue(h("desktop-rvaf7exq"))       # the app's shell off
        self.assertTrue(h("pbkztc5rkx"))             # ...and its panel
        self.assertFalse(h("yzhfb4a8qbj"))           # web pages default on
        self.assertFalse(h("tune1", away=True))      # the car default on

    def test_nabu_is_listed_even_though_it_never_polls(self):
        ns, st, _, _ = build()
        house(ns, st)
        ns["_RADIO"].update(voice_to="box", reply_to="box")
        state = ns["air_receivers_state"]()
        ids = [r["id"] for r in state["receivers"]]
        self.assertEqual(ids, ["pinetab", "desktop", "web", "car", "nabu", "box"])
        nabu = row(state, "nabu")
        self.assertTrue(nabu["audible"])
        self.assertIn("DJs", nabu["detail"])
        self.assertFalse(row(state, "box")["audible"])   # one road, the Nabu has it

    def test_operator_state_in_two_taps_and_it_persists(self):
        ns, st, routed, _ = build()
        house(ns, st, pinetab=True, desktop=True)
        ns["_RADIO"].update(voice_to="box", reply_to="box")    # DJs on the Nabu
        a = post(ns, {"id": "nabu", "audible": False})
        self.assertTrue(a["ok"])
        self.assertEqual(routed[-1], {"voice": "here", "reply": "here"})
        self.assertFalse(row(a, "nabu")["audible"])
        b = post(ns, {"id": "desktop", "audible": False})
        self.assertTrue(b["ok"])
        self.assertEqual(st["settings"]["terminals"]["desktop"]["play"], False)
        self.assertEqual(st["settings"]["air_receivers"]["speaker_streams"],
                         ["voice", "reply"])
        # survives a reload: a fresh read of the stored settings says the same
        ns["_AIR_RECV_CACHE"].update(at=0.0, eff_at=0.0)
        again = ns["air_receivers_state"]()
        self.assertTrue(row(again, "pinetab")["audible"])
        self.assertFalse(row(again, "desktop")["audible"])
        self.assertFalse(row(again, "nabu")["audible"])
        self.assertTrue(ns["air_hushed"]("pbkztc5rkx"))
        self.assertFalse(ns["air_hushed"]("pbnnmzpnrf"))
        # and the Nabu comes back carrying exactly what it carried
        c = post(ns, {"id": "nabu", "audible": True})
        self.assertEqual(routed[-1], {"voice": "box", "reply": "box",
                                      "voice_device": "nabu"})
        self.assertTrue(row(c, "nabu")["audible"])

    def test_only_the_pinetab_makes_it_the_active_radio(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=True)
        out = post(ns, {"only": "pinetab"})
        self.assertEqual(out["active"], "pinetab")
        self.assertEqual(out["owner"], "pbnnmzpnrf")
        self.assertTrue(row(out, "pinetab")["active"])
        for rid in ("desktop", "web"):
            self.assertFalse(row(out, rid)["audible"], rid)
        self.assertTrue(row(out, "car")["audible"])      # not in the room
        self.assertEqual(st["settings"]["air_receivers"].get("web"), False)

    def test_the_last_audible_receiver_cannot_be_switched_off(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=False)
        post(ns, {"id": "web", "audible": False})
        post(ns, {"id": "car", "audible": False})
        out = post(ns, {"id": "pinetab", "audible": False})
        self.assertFalse(out["ok"])
        self.assertIn("nothing sounding", out["why"])
        self.assertTrue(st["settings"]["terminals"]["pinetab"]["play"])

    def test_several_on_is_a_choice_not_a_fault(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=True)
        self.assertEqual(ns["audio_owner"](), "")        # nobody gagged
        for who in ("pbnnmzpnrf", "desktop-rvaf7exq", "yzhfb4a8qbj"):
            self.assertFalse(ns["air_hushed"](who), who)

    def test_a_house_nobody_has_touched_keeps_the_old_exclusive(self):
        # the live shape after the 08:15Z restart: PineTab play=true, the app
        # play=false, one web page, nothing stored for web pages
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=False)
        self.assertEqual(ns["audio_owner"](), "pbnnmzpnrf")
        state = ns["air_receivers_state"]()
        self.assertEqual(state["active"], "pinetab")
        self.assertFalse(row(state, "web")["sounding"])   # gagged, as before

    def test_web_pages_switched_on_by_hand_are_a_choice(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=False)
        post(ns, {"id": "web", "audible": False})
        post(ns, {"id": "web", "audible": True})
        self.assertEqual(ns["audio_owner"](), "")
        self.assertTrue(row(ns["air_receivers_state"](), "web")["sounding"])

    def test_one_on_still_gets_the_table_nomination(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=False)
        post(ns, {"id": "web", "audible": False})
        self.assertEqual(ns["audio_owner"](), "pbnnmzpnrf")

    def test_nothing_switched_on_is_here_so_nobody_is_hushed(self):
        ns, st, _, _ = build()
        house(ns, st, pinetab=True, desktop=False)
        post(ns, {"id": "web", "audible": False})
        ns["_LISTENER_SEEN"]["pbnnmzpnrf"]["at"] = time.time() - 200  # tablet away
        ns["_AIR_RECV_CACHE"].update(at=0.0, eff_at=0.0)
        self.assertFalse(ns["air_hushed"]("pbkztc5rkx"))
        self.assertFalse(ns["air_hushed"]("yzhfb4a8qbj"))
        self.assertTrue(ns["air_receivers_state"]()["rescued"])

    def test_heard_receipts_keep_flowing_with_only_the_pinetab_audible(self):
        ns, st, _, receipts = build()
        house(ns, st, pinetab=True, desktop=False)
        post(ns, {"only": "pinetab"})
        ns["_PAGE_DELIVERIES"]["d1"] = {"delivery_id": "d1", "speech": True,
                                        "state": "published", "clip": {}}
        ack = ns["page_playback_ack"]
        # the hushed pages play muted; the tablet plays out loud
        t0 = time.time()
        for seq, (who, muted, vol) in enumerate((
                ("pbkztc5rkx", True, 0.0), ("yzhfb4a8qbj", True, 0.0),
                ("pbnnmzpnrf", False, 1.0), ("pbkztc5rkx", True, 0.0)), 1):
            ack({"event": "playing", "listener_id": who, "delivery_id": "d1",
                 "volume": 1.0, "audible_volume": vol, "muted": muted,
                 "current_time": seq * 1.0, "sequence": seq})
        self.assertGreaterEqual(ns["_DIALOGUE_HEARD"][0], t0)       # #1231
        self.assertEqual(receipts, ["d1"])        # line receipt: the tablet's
        self.assertEqual(ns["_PAGE_DELIVERIES"]["d1"]["state"], "playing")
        wedge = ns["page_wedge_state"]()
        self.assertGreaterEqual(wedge["heard_at"], round(t0, 1) - 0.1)
        self.assertLess(wedge["quiet"], 5)
        self.assertFalse(wedge["wedged"])
        state = ns["air_receivers_state"]()
        self.assertIsNotNone(row(state, "pinetab")["heard_ago"])
        self.assertIsNone(row(state, "desktop")["heard_ago"])
        # #1332 does not take the air off the one audible receiver
        ns["_OWNER_RUN"].update(who="pbnnmzpnrf", since=time.time() - 120)
        self.assertEqual(ns["audio_owner"](), "pbnnmzpnrf")

    def test_the_pages_and_the_settings_carry_it(self):
        self.assertEqual(S.count("[airplayers:gate]"), 2)       # panel + tune page
        self.assertEqual(S.count("const gagged = !!(clock && clock.hushed)"), 2)
        self.assertIn('"air_receivers": validate_air_receivers(data.get("air_receivers"))', S)
        self.assertIn('"hushed": air_hushed(listener[:64], _away) if listener else False', S)
        self.assertIn("[airplayers:solo]", S)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
