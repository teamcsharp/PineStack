"""The two transport wrappers the app.py patch installs, executed.

The patch script is not run here and app.py is never imported - it is 9.7 MB
and needs the whole station. What IS executed is the exact source text the
patch inserts, in a namespace holding stand-ins for the handful of app.py
globals it touches. So the wrappers are tested as code rather than as a
description of code, and a typo in the patch fails here rather than on air.

The patch lives outside the repository on purpose: the station is
broadcasting and the caller applies every app.py change by hand. Point
SPARK_ADMISSION_PATCH at it, or leave it where the agent wrote it; without
it these tests skip and say so.
"""
import asyncio
import os
import re
import sys
import tempfile
import time
import unittest
from functools import wraps
from pathlib import Path
from typing import Any

import broadcast_admission as ba

CANDIDATES = [
    os.getenv("SPARK_ADMISSION_PATCH", ""),
    str(Path(tempfile.gettempdir()) / "claude" / "patch_admission.py"),
    r"C:\Users\EHMECK~1\AppData\Local\Temp\claude"
    r"\--10-89-1-246-ehm-eckx-pinevoice-stack-spark-agent"
    r"\4c062de1-24db-4acb-9996-7567ccd60535\scratchpad\patch_admission.py",
]


def find_patch():
    for name in CANDIDATES:
        if name and Path(name).is_file():
            return Path(name)
    return None


PATCH = find_patch()


def load_blocks():
    """The patch's own BOOTSTRAP/BOX_WRAPPER/PAGE_WRAPPER strings, taken by
    importing it as a module. It has no side effects at import: everything
    happens under `if __name__ == "__main__"`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_patch_admission", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Station:
    """The few app.py globals the inserted code actually touches."""

    def __init__(self, room: Path):
        self.room = room
        self.media = room / "voice_media"
        self.media.mkdir(parents=True, exist_ok=True)
        self.logs = []
        self.activity = []
        self.box_returns = "media_player.pine"
        self.box_raises = None

    def namespace(self):
        station = self

        async def _play_on_box(path, sig, reply=False, replay=False):
            if station.box_raises:
                raise station.box_raises
            return station.box_returns

        def page_feed_append(clip):
            return "delivery-" + str(len(station.logs) + 1)

        return {
            "__name__": "app_stub",
            "Any": Any, "Path": Path, "os": os, "sys": sys, "time": time,
            "re": re, "wraps": wraps, "asyncio": asyncio,
            "data_path": lambda *parts: station.room.joinpath(*parts),
            "VOICE_MEDIA_DIR": station.media,
            "MEDIA_KEY_SHAPE": re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{1,4}\Z"),
            "_RADIO": {"voice_to": "box", "voice_device": "pine", "box_talk": True},
            "_LAST_PLAYOUT": {"key": "", "ratio": 1.0, "ok": True,
                              "evidence": "blocking_call_duration",
                              "audible_confirmed": None, "evidence_note": ""},
            "_ANNOUNCE_LAST": {"error": ""},
            "_clip_seconds": lambda path: 12.0,
            "_played_out_key": lambda path: str(path).split("?")[0].rsplit("/", 1)[-1],
            "pipeline_log": lambda kind, text, extra="": station.logs.append(
                (kind, text, extra)),
            "note_activity": lambda stage, detail="": station.activity.append(
                (stage, detail)),
            "_play_on_box": _play_on_box,
            "page_feed_append": page_feed_append,
        }

    def clip(self, name, seconds=12.0, rate=16000):
        frames = int(seconds * rate)
        data = b"\x00\x00" * frames
        header = (b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt "
                  + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
                  + (1).to_bytes(2, "little") + rate.to_bytes(4, "little")
                  + (rate * 2).to_bytes(4, "little") + (2).to_bytes(2, "little")
                  + (16).to_bytes(2, "little") + b"data"
                  + len(data).to_bytes(4, "little"))
        (self.media / name).write_bytes(header + data)
        return "/media/" + name


@unittest.skipIf(PATCH is None,
                 "patch_admission.py not found; set SPARK_ADMISSION_PATCH")
class TransportWrapperTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="admission-patch-")
        self.addCleanup(self.dir.cleanup)
        self.station = Station(Path(self.dir.name))
        self.space = self.station.namespace()
        blocks = load_blocks()
        self.blocks = blocks
        for name in ("BOOTSTRAP", "BOX_WRAPPER", "PAGE_WRAPPER"):
            exec(compile(getattr(blocks, name), "<" + name + ">", "exec"),
                 self.space)
        self.mode(" ")

    def mode(self, words):
        path = Path(self.dir.name) / "broadcast_admission" / "mode"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(words, encoding="utf-8")
        self.space["_ADMISSION_MODE_READ"][0] = 0.0     # force a re-read

    def box(self, path, sig="s", **kw):
        return asyncio.run(self.space["_play_on_box"](path, sig, **kw))

    def page(self, clip):
        return self.space["page_feed_append"](clip)

    def controller(self):
        return self.space["admission_controller"]()

    def round_rows(self, ids):
        rows, at = [], 0.0
        for line in ids:
            rows.append({"id": line, "from": at, "until": at + 4.0,
                         "clip_tail": 0.4, "who": "dj", "text": line})
            at += 4.0
        return rows

    # ------------------------------------------------------------- shape

    def test_the_patch_blocks_all_compile_against_a_bare_namespace(self):
        for name in ("admission_controller", "admission_ticket",
                     "admission_delivery", "admission_admit_round",
                     "admission_state", "_play_on_box", "page_feed_append"):
            self.assertIn(name, self.space, name + " was not installed")

    def test_the_default_mode_is_observe_and_refuses_nothing(self):
        self.mode("observe")
        controller = self.controller()
        self.assertEqual(controller.mode, "observe")
        path = self.station.clip("loose.wav")
        self.assertEqual(self.box(path), "media_player.pine")
        counts = controller.stats()["counts"]
        self.assertEqual(counts.get("would_refuse:unadmitted"), 1)

    def test_switching_the_mode_file_needs_no_restart(self):
        path = self.station.clip("loose.wav")
        self.mode("observe")
        self.assertEqual(self.box(path), "media_player.pine")
        self.mode("enforce")
        self.assertEqual(self.box(path), "", "an unadmitted dispatch is refused")
        self.assertIn(("held", "not admitted to the broadcast sequence "
                       "- kept for the page"), self.station.activity)
        self.mode("observe")
        self.assertEqual(self.box(path), "media_player.pine")

    def test_off_unhooks_the_controller_entirely(self):
        self.mode("off")
        self.assertIsNone(self.controller())
        path = self.station.clip("loose.wav")
        self.assertEqual(self.box(path), "media_player.pine")

    def test_a_single_lane_can_be_enforced_alone(self):
        self.mode("enforce sfx")
        speech = self.station.clip("round.wav")
        sting = self.station.clip("sting.wav")
        self.assertEqual(self.box(speech), "media_player.pine",
                         "the speech lane is still observed")
        self.assertEqual(self.box("/sfx/" + "sting.wav"), "",
                         "the sfx lane is enforced")

    # ------------------------------------------------- one occurrence only

    def test_an_admitted_round_is_claimed_rather_than_re_admitted(self):
        path = self.station.clip("round-88.wav")
        rows = self.round_rows(["a", "b", "c"])
        oid = self.space["admission_admit_round"](
            {"path": path, "sig": "abc"}, rows, 12.0, producer="test")
        self.assertTrue(oid)
        self.assertEqual(self.box(path, "abc"), "media_player.pine")
        controller = self.controller()
        self.assertEqual(controller.stats()["occurrences"], 1)
        row = controller.occurrence(oid)
        self.assertEqual(row["state"], "finished")
        self.assertEqual(row["outcome"], "accepted")
        self.assertEqual([c["line_id"] for c in row["cues"]], ["a", "b", "c"])

    def test_the_page_and_the_box_are_two_routes_onto_one_occurrence(self):
        path = self.station.clip("round-88.wav")
        rows = self.round_rows(["a", "b"])
        self.page({"url": path + "?t=abc", "text": "a conversation",
                   "speech": True, "stream": {"length": 8.0, "rows": rows}})
        self.box(path, "abc")
        controller = self.controller()
        self.assertEqual(controller.stats()["occurrences"], 1,
                         "two transports, one committed line")

    def test_the_page_carries_the_occurrence_back_onto_the_clip(self):
        path = self.station.clip("round-88.wav")
        clip = {"url": path + "?t=abc", "text": "a conversation", "speech": True,
                "stream": {"length": 8.0, "rows": self.round_rows(["a", "b"])}}
        self.page(clip)
        self.assertTrue(clip.get("playback_occurrence_id"))
        self.assertIsInstance(clip.get("playback_position"), int)

    def test_a_sting_played_twice_is_two_occurrences(self):
        path = self.station.clip("bell.wav", seconds=1.5)
        self.box(path, "x")
        time.sleep(0.01)
        self.box(path, "x")
        controller = self.controller()
        self.assertEqual(controller.stats()["occurrences"], 2)
        rows = controller.cue_map()["occurrences"]
        self.assertNotEqual(rows[0]["position"], rows[1]["position"])

    # --------------------------------------------------------- receipts

    def test_a_box_that_declines_is_recorded_as_blocked_not_delivered(self):
        path = self.station.clip("round.wav")
        self.station.box_returns = ""
        self.space["_ANNOUNCE_LAST"]["error"] = "box is quiet"
        self.assertEqual(self.box(path), "")
        row = self.controller().cue_map()["occurrences"][-1]
        self.assertEqual(row["outcome"], "blocked")
        self.assertIn("box is quiet", row["delivery"]["evidence"]["note"])

    def test_a_transport_acceptance_is_never_recorded_as_delivered(self):
        path = self.station.clip("round.wav")
        self.space["_LAST_PLAYOUT"].update(
            key="round.wav", evidence="home_assistant_command_accepted",
            audible_confirmed=False)
        self.box(path)
        row = self.controller().cue_map()["occurrences"][-1]
        self.assertEqual(row["outcome"], "accepted")
        self.assertNotEqual(row["outcome"], ba.DELIVERED)
        self.assertIs(row["delivery"]["audible_confirmed"], False)

    def test_a_throwing_transport_records_a_failure_and_re_raises(self):
        path = self.station.clip("round.wav")
        self.station.box_raises = RuntimeError("the socket dropped")
        with self.assertRaises(RuntimeError):
            self.box(path)
        row = self.controller().cue_map()["occurrences"][-1]
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("the socket dropped", row["delivery"]["evidence"]["error"])

    def test_a_meter_holding_another_clips_key_is_not_read_as_this_clips(self):
        # #807: _LAST_PLAYOUT is shared, and a concurrent ack stamps it with
        # ITS key. The wrapper must not credit this occurrence with it.
        path = self.station.clip("round.wav")
        self.space["_LAST_PLAYOUT"].update(key="somebody-else.wav", ratio=0.1,
                                           audible_confirmed=True)
        self.box(path)
        row = self.controller().cue_map()["occurrences"][-1]
        self.assertIsNone(row["delivery"]["audible_confirmed"])
        self.assertIn("another clip's key", row["delivery"]["evidence"]["evidence"])

    # ------------------------------------------------- lanes and exemptions

    def test_a_reply_is_exempt_even_under_full_enforcement(self):
        self.mode("enforce order")
        self.assertEqual(self.box("/media/ack.wav", "x", reply=True),
                         "media_player.pine")
        self.assertEqual(self.page({"url": "/media/ack.wav", "kind": "reply"}),
                         "delivery-1")

    def test_the_lane_is_read_off_the_path_and_the_kind(self):
        lane = self.space["_admission_lane"]
        self.assertEqual(lane("/sfx/bell.wav"), "sfx")
        self.assertEqual(lane("/media/abc.wav", "reply"), "reply")
        self.assertEqual(lane("/media/abc.wav", "banter"), "speech")
        self.assertEqual(lane("/media/station_id-3.wav"), "station")

    # -------------------------------------------------------- the census

    def test_the_producer_is_named_from_its_own_stack_frame(self):
        path = self.station.clip("loose.wav")

        async def dj_sting_stub():
            return await self.space["_play_on_box"](path, "x")

        asyncio.run(dj_sting_stub())
        refusals = self.controller().refusals()
        self.assertTrue(refusals)
        self.assertIn("dj_sting_stub", refusals[-1]["detail"]["producer"])

    def test_admission_state_is_json_shaped_and_says_when_it_is_off(self):
        import json
        self.mode("observe")
        self.box(self.station.clip("round.wav"))
        payload = self.space["admission_state"](12)
        self.assertTrue(payload["available"])
        json.dumps(payload)
        self.mode("off")
        off = self.space["admission_state"](12)
        self.assertFalse(off["available"])
        self.assertEqual(off["mode"], "off")

    def test_a_route_change_bumps_the_ownership_generation(self):
        self.controller()                        # learn the current route
        before = self.controller().generation
        self.space["_RADIO"]["voice_to"] = "here"
        self.space["_ADMISSION_MODE_READ"][0] = 0.0
        self.assertGreater(self.controller().generation, before)

    def test_a_broken_controller_never_stops_the_air(self):
        # Whatever goes wrong inside the gate, the clip still goes out.
        self.space["_ADMISSION"] = object()      # no gate methods at all
        path = self.station.clip("round.wav")
        self.assertEqual(self.box(path), "media_player.pine")


@unittest.skipIf(PATCH is None,
                 "patch_admission.py not found; set SPARK_ADMISSION_PATCH")
class PatchTextTests(unittest.TestCase):
    def test_every_block_is_bounded_by_its_marker_so_revert_is_mechanical(self):
        blocks = load_blocks()
        for name in ("BOOTSTRAP", "BOX_WRAPPER", "PAGE_WRAPPER", "BURST_CALL",
                     "DJ_STATE", "DIAG", "ROUTE"):
            body = getattr(blocks, name)
            self.assertIn(blocks.MARK, body, name)
            self.assertIn(blocks.END, body, name)

    def test_the_patch_never_emits_a_carriage_return(self):
        blocks = load_blocks()
        for name in ("BOOTSTRAP", "BOX_WRAPPER", "PAGE_WRAPPER", "BURST_CALL",
                     "DJ_STATE", "DIAG", "ROUTE"):
            self.assertNotIn("\r", getattr(blocks, name), name)

    @staticmethod
    def sample(blocks):
        """A synthetic app.py: every one of the seven anchors, exactly once,
        in the order they appear in the real file. Enough to exercise apply
        and revert without a 9.7 MB copy."""
        return "".join((
            blocks.ANCHOR_BOOTSTRAP,
            "\n\n",
            blocks.ANCHOR_BOX,
            "    return False\n\n\n",
            blocks.ANCHOR_PAGE,
            "    return {}\n\n\n",
            "def burst():\n",
            "                try:\n                    pass\n",
            blocks.ANCHOR_BURST,
            "\n\ndef state():\n    return {\n",
            blocks.ANCHOR_DJ_STATE,
            "    }\n\n\ndef context():\n",
            blocks.ANCHOR_DIAG,
            "\n\n",
            blocks.ANCHOR_ROUTE,
            "    return 0.0\n"))

    def test_applying_twice_is_a_no_op(self):
        blocks = load_blocks()
        sample = self.sample(blocks)
        once, done, skipped = blocks.apply(sample)
        self.assertEqual(len(done), 7, done)
        self.assertEqual(skipped, [])
        twice, done2, skipped2 = blocks.apply(once)
        self.assertEqual(twice, once)
        self.assertEqual(done2, [])
        self.assertEqual(len(skipped2), 7)

    def test_a_moved_anchor_refuses_rather_than_matching_loosely(self):
        blocks = load_blocks()
        with self.assertRaises(SystemExit) as caught:
            blocks.apply("nothing in here resembles app.py\n")
        self.assertIn("ANCHOR NOT UNIQUE", str(caught.exception))

    def test_a_duplicated_anchor_also_refuses(self):
        blocks = load_blocks()
        doubled = blocks.ANCHOR_BOOTSTRAP + blocks.ANCHOR_BOOTSTRAP
        with self.assertRaises(SystemExit) as caught:
            blocks.apply(doubled)
        self.assertIn("found 2 times", str(caught.exception))

    def test_revert_removes_exactly_what_apply_added(self):
        # BYTE FOR BYTE. A revert that leaves a stray blank line behind is a
        # revert that cannot be trusted to have left nothing else behind.
        blocks = load_blocks()
        sample = self.sample(blocks)
        patched, _, _ = blocks.apply(sample)
        back, removed = blocks.revert(patched)
        self.assertEqual(removed, 7)
        self.assertEqual(back, sample)


if __name__ == "__main__":
    unittest.main()
