"""[s3-inject] The honest forced card (coverage GAPs 8 and 11).

One shared door - System3Runtime.injected_node - writes "forced: no roll -
injected by <system> because <reason>" as an INJECT observation ON the
conversation executing at that timeline point (the ONE TREE rule), never
fake dice.  Proven here: the helper's anchor ladder, the standing-surface
dedupe (Pine Cam), that an injected node never touches a replay, and every
wired door - the dead-air rescue, boot recovery, the Pine Cam standing
node (app.py's own function bodies, executed against stubs) and MX Live's
set start / level-gate cover / stop (pinelive.py driven directly).

Run one module at a time, niced, in the container tree:
  PYTHONPATH=/tmp/cover_a nice -n 19 timeout 600 \
      python -m unittest tests.test_injected_node_2026_09_28 -v
"""
import asyncio
import json
from pathlib import Path
import re
import tempfile
import time
import unittest

import system3
import system3_runtime
import pinelive

HERE = Path(__file__).resolve().parent.parent


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 6,
            "topic": "the box men", "keywords": ["box"], "material": {}}
    base.update(over)
    return base


def settings(**over):
    raw = {"mode": "active", "test_seed": "inject-1"}
    raw.update(over)
    return system3.normalise_settings(raw)


def plan(seed="inject-1", cid="inj-conv"):
    return system3.plan_scene(inputs(), system3.default_config(),
                              settings(test_seed=seed), conversation_id=cid)


def make_rt(root):
    ns = {"data_path": lambda *p: Path(root).joinpath(*p),
          "pipeline_log": lambda *a, **k: None}
    host = system3_runtime._Host(ns)
    rt = system3_runtime.System3Runtime(host)
    return rt, ns


def drain():
    """Wait for every queued store job (the pool is one thread, FIFO)."""
    system3_runtime._STORE_POOL.submit(lambda: None).result(timeout=10)


def injects_of(conv):
    return [o for o in conv.get("observations_air") or [] if o.get("family") == "INJECT"]


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.rt, self.ns = make_rt(self.tmp.name)
        self.conv = plan()
        self.rt.store.save_conversation(self.conv)

    def tearDown(self):
        drain()
        try:
            self.rt.store.db.close()   # Windows: the open handle blocks rmtree
        except Exception:  # noqa: BLE001
            pass
        self.tmp.cleanup()

    def test_explicit_conversation_and_honest_card(self):
        t0 = self.conv["turns"][0]["turn_id"]
        ok = self.rt.injected_node("the dead-air rescue", "the room was quiet 45 s",
                                   kind="rescue", conversation_id="inj-conv", turn_id=t0,
                                   at=1790000000.0, extra={"road": "manager", "lines": 3})
        self.assertTrue(ok)
        drain()
        got = self.rt.store.conversation("inj-conv")
        cards = injects_of(got)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["kind"], "observation")
        self.assertEqual(card["card"],
                         "forced: no roll - injected by the dead-air rescue "
                         "because the room was quiet 45 s")
        self.assertEqual(card["by"], "the dead-air rescue")
        self.assertEqual(card["authority"], "forced")
        self.assertEqual(card["turn_id"], t0)
        self.assertEqual(card["at"], 1790000000.0)
        self.assertEqual(card["road"], "manager")
        # never fake dice: no rng, no stages, no draws on the card
        for key in ("rng", "stages", "draws", "dice", "selected"):
            self.assertNotIn(key, card)

    def test_line_link_anchors_its_own_round(self):
        t0 = self.conv["turns"][0]["turn_id"]
        self.rt.store.add_lines([{"line_id": "lid-1", "conversation_id": "inj-conv",
                                  "turn_id": t0, "block": 5, "ord": 0, "sid": "",
                                  "who": "dj", "text": "hello", "at": time.time()}])
        self.rt.injected_node("boot recovery", "the restart cut the page feed",
                              kind="boot", line_id="lid-1")
        drain()
        cards = injects_of(self.rt.store.conversation("inj-conv"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["anchored"], "its own line's link")
        self.assertEqual(cards[0]["turn_id"], t0)

    def test_speaking_now_anchors_the_line_on_air(self):
        t0 = self.conv["turns"][0]["turn_id"]
        self.ns["_SPEAKING_NOW"] = {"id": "lid-air"}
        self.ns["_S3_LINE_BY_ID"] = {"lid-air": {"conversation_id": "inj-conv",
                                                 "turn_id": t0, "mode": "active"}}
        self.rt.injected_node("the level gate", "the input was silent for 15 s")
        drain()
        cards = injects_of(self.rt.store.conversation("inj-conv"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["anchored"], "the line on air")

    def test_recent_then_store_fallbacks(self):
        self.rt.recent["inj-conv"] = self.conv
        self.rt.injected_node("MX Live", "the set has the air")
        drain()
        self.assertEqual(len(injects_of(self.rt.store.conversation("inj-conv"))), 1)
        self.rt.recent.clear()
        self.rt.injected_node("MX Live", "the set gave the air back")
        drain()
        self.assertEqual(len(injects_of(self.rt.store.conversation("inj-conv"))), 2,
                         "with nothing on air the newest stored round holds the node")

    def test_standing_dedupe_is_per_kind_and_rests(self):
        self.rt.recent["inj-conv"] = self.conv
        a = self.rt.injected_node("Pine Cam", "fixed surface: Pine Cam, live camera - "
                                  "no roll by design", kind="surface", standing=True)
        b = self.rt.injected_node("Pine Cam", "fixed surface: Pine Cam, live camera - "
                                  "no roll by design", kind="surface", standing=True)
        self.assertTrue(a)
        self.assertFalse(b, "a standing card rests half an hour")
        drain()
        cards = injects_of(self.rt.store.conversation("inj-conv"))
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["standing"])

    def test_replay_is_untouched_by_an_injected_node(self):
        before = system3.replay(json.loads(json.dumps(self.conv)), system3.default_config())
        self.assertTrue(before["ok"], before.get("why"))
        events_before = [e["event_id"] for e in self.conv["decision_events"]]
        self.rt.injected_node("the dead-air rescue", "dead air 30 s",
                              conversation_id="inj-conv")
        drain()
        stored = self.rt.store.conversation("inj-conv")
        self.assertEqual([e["event_id"] for e in stored["decision_events"]], events_before,
                         "the decision chain is exactly what it was")
        again = system3.replay(json.loads(json.dumps(stored)), system3.default_config())
        self.assertTrue(again["ok"], again.get("why"))

    def test_never_raises_without_a_round_anywhere(self):
        # empty store, nothing recent, nothing on air: the write is dropped,
        # counted, and the caller is never burnt
        ok = self.rt.injected_node("the dead-air rescue", "quiet")
        drain()
        self.assertTrue(ok)   # queued; the job found nothing and filed the metric
        self.assertEqual(self.rt.metrics.get("injected", 0) +
                         self.rt.metrics.get("inject_dropped", 0), 1)


def app_slice(name, kind="async"):
    """One function's source out of app.py, to run against stubs."""
    src = (HERE / "app.py").read_bytes().decode("utf-8")
    head = ("async def %s(" if kind == "async" else "def %s(") % name
    at = src.index(head)
    nxt = re.compile(r"\n(?:async def |def |@app\.|[A-Z_]+[A-Z0-9_]* *[:=])")
    m = nxt.search(src, at + len(head))
    return src[at:m.start()] + "\n"


class AppDoorTests(unittest.TestCase):
    """The wired doors in app.py, executed against stubs."""

    def test_dead_air_rescue_writes_the_card(self):
        calls = []
        g = {
            "time": time, "asyncio": asyncio,
            "_RESCUE_AT": [0.0], "DEAD_AIR_RESCUE_REST": 0.0,
            "radio_paused": lambda: False, "_RADIO": {"on": True, "now": {}},
            "dead_air_stock": lambda: {"manager": 1},
            "DEAD_AIR_RESCUE_ROADS": ("manager",), "RESCUE_ROADS_OPEN": ("manager",),
            "schedule_take": lambda: {},
            "pipeline_log": lambda *a, **k: None, "repair_note": lambda *a, **k: None,
            "system3_injected_node": lambda **kw: calls.append(kw),
        }

        async def _ready_shelf_air(kind, track, rescue=False):
            return ["said one", "said two"]
        g["_ready_shelf_air"] = _ready_shelf_air
        exec(compile(app_slice("dead_air_rescue"), "app-slice", "exec"), g)
        went = asyncio.run(g["dead_air_rescue"](41.0))
        self.assertEqual(went, "manager")
        self.assertEqual(len(calls), 1)
        kw = calls[0]
        self.assertEqual(kw["by"], "the dead-air rescue")
        self.assertEqual(kw["kind"], "rescue")
        self.assertIn("the room was quiet 41 s", kw["why"])
        self.assertIn("a finished manager round went out off the shelf", kw["why"])
        self.assertEqual(kw["extra"], {"road": "manager", "lines": 2})
        self.assertLessEqual(kw["at"], time.time())

    def test_dead_air_rescue_torrent_floor_wording(self):
        calls = []
        g = {
            "time": time, "asyncio": asyncio,
            "_RESCUE_AT": [0.0], "DEAD_AIR_RESCUE_REST": 0.0,
            "radio_paused": lambda: False, "_RADIO": {"on": True, "now": {}},
            "dead_air_stock": lambda: {"news": 1},
            "DEAD_AIR_RESCUE_ROADS": ("news",), "RESCUE_ROADS_OPEN": ("news",),
            "schedule_take": lambda: {},
            "pipeline_log": lambda *a, **k: None, "repair_note": lambda *a, **k: None,
            "system3_injected_node": lambda **kw: calls.append(kw),
        }

        async def _ready_shelf_air(kind, track, rescue=False):
            return ["one"]
        g["_ready_shelf_air"] = _ready_shelf_air
        exec(compile(app_slice("dead_air_rescue"), "app-slice", "exec"), g)
        asyncio.run(g["dead_air_rescue"](0.0))
        self.assertEqual(len(calls), 1)
        self.assertIn("the show ran out of things to say", calls[0]["why"])

    def test_boot_recovery_writes_one_card_naming_the_count(self):
        calls = []
        settled = []
        saved_rows = [{"delivery_id": "d1", "row_id": "lid-a", "ts": 1, "url": "/m/a.mp3"},
                      {"delivery_id": "d2", "row_id": "lid-b", "ts": 2, "url": "/m/b.mp3"}]
        g = {
            "time": time, "asyncio": asyncio,
            "page_recovery_read": lambda: [dict(r) for r in saved_rows],
            "_RADIO": {"on": True, "voice_to": "page", "voice_cut_ms": 0},
            "radio_paused": lambda: False,
            "_floor_take": None, "_floor_drop": lambda o: None,
            "page_recovery_prepare_row": lambda clip: None,
            "admission_admit_line": lambda *a, **k: None,
            "page_feed_append": lambda clip: clip["delivery_id"],
            "page_recovery_chat_rows": lambda clip, delivery: None,
            "_PAGE_AIR_UNTIL": [0.0],
            "system3_injected_node": lambda **kw: calls.append(kw),
        }

        async def _floor_take(why):
            return "owned"

        async def _paged_settle(until):
            settled.append(until)
        g["_floor_take"] = _floor_take
        g["_paged_settle"] = _paged_settle
        exec(compile(app_slice("page_recovery_start"), "app-slice", "exec"), g)
        asyncio.run(g["page_recovery_start"]())
        self.assertEqual(settled, [0.0], "the settle still runs after the card")
        self.assertEqual(len(calls), 1)
        kw = calls[0]
        self.assertEqual(kw["by"], "boot recovery")
        self.assertEqual(kw["kind"], "boot")
        self.assertIn("2 preserved deliveries republished", kw["why"])
        self.assertEqual(kw["line_id"], "lid-a")
        self.assertEqual(kw["extra"], {"deliveries": 2})

    def test_cam_standing_rising_edge_only(self):
        calls = []
        src = (HERE / "app.py").read_bytes().decode("utf-8")
        at = src.index('_PINELINK_S3_STAND = {"was": False}')
        end = src.index('@app.post("/api/pinelink/on-air")', at)
        g = {"system3_injected_node": lambda **kw: calls.append(kw)}
        exec(compile(src[at:end], "app-slice", "exec"), g)
        fn = g["_s3_cam_standing"]
        fn(False)
        self.assertEqual(calls, [])
        fn(True)                       # the feed comes up: one standing card
        fn(True)                       # still up: nothing
        self.assertEqual(len(calls), 1)
        kw = calls[0]
        self.assertEqual(kw["by"], "Pine Cam")
        self.assertTrue(kw["standing"])
        self.assertEqual(kw["kind"], "surface")
        self.assertIn("fixed surface: Pine Cam, live camera - no roll by design", kw["why"])
        fn(False)                      # the feed drops
        fn(True)                       # ...and (re)starts: the edge writes again
        self.assertEqual(len(calls), 2)


class PineLiveDoorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pl = pinelive.PineLive(Path(self.tmp.name))
        self.calls = []
        self._had = dict(pinelive._G)
        pinelive._G["system3_injected_node"] = lambda **kw: self.calls.append(kw)
        pinelive._G["_RADIO"] = {"on": True, "now": {}, "queue": []}
        pinelive._G["dj_skip"] = lambda: None

    def tearDown(self):
        pinelive._G.clear()
        pinelive._G.update(self._had)
        self.tmp.cleanup()

    def test_take_air_writes_set_start(self):
        self.pl.event = {"id": "mxlive-t", "folder": "f", "armed": True}
        self.pl.phase = "arming"
        self.pl._take_air("the input is heard")
        starts = [c for c in self.calls if c.get("kind") == "set-start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["by"], "MX Live")
        self.assertIn("the set has the air (the input is heard)", starts[0]["why"])

    def test_level_gate_cover(self):
        self.pl.event = {"id": "mxlive-t", "folder": "f", "armed": True}
        self.pl.phase = "live"
        self.pl._fallback("silence", "the input was silent for 15 s; the station "
                                     "took the air back")
        covers = [c for c in self.calls if c.get("kind") == "cover"]
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0]["by"], "the level gate")
        self.assertIn("took the air back", covers[0]["why"])
        self.assertIn("the station's own playout covers the set", covers[0]["why"])
        self.assertEqual(self.pl.phase, "fallback")

    def test_stop_writes_set_stop_only_when_live(self):
        self.pl.event = {"id": "mxlive-t", "folder": "f", "armed": True}
        self.pl.phase = "live"
        self.pl.stop("the stop control")
        stops = [c for c in self.calls if c.get("kind") == "set-stop"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["by"], "MX Live")
        self.assertIn("the operator ended the set (the stop control)", stops[0]["why"])
        # a stop while the set never had the air says nothing
        self.calls.clear()
        self.pl.event = {"id": "mxlive-u", "folder": "f", "armed": True}
        self.pl.phase = "arming"
        self.pl.stop("the stop control")
        self.assertEqual([c for c in self.calls if c.get("kind") == "set-stop"], [])

    def test_doors_never_raise_without_system3(self):
        pinelive._G.pop("system3_injected_node", None)
        self.pl.event = {"id": "mxlive-t", "folder": "f", "armed": True}
        self.pl.phase = "live"
        self.pl._fallback("dropout", "the input stopped arriving for 3.0 s; the "
                                     "station took the air back")
        self.assertEqual(self.pl.phase, "fallback")


if __name__ == "__main__":
    unittest.main()
