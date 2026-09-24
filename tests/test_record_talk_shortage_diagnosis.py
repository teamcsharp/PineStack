"""Hermetic evidence for the record-talk supply and reporting mismatch.

These tests execute only the named app.py functions with stand-in stores. They
do not import app.py, call the station, or write to its data directory.
"""

from __future__ import annotations

import ast
import re
import time
import unittest
from pathlib import Path
from typing import Any

import track_talk_segment as talk


APP = Path(__file__).resolve().parents[1] / "app.py"


def app_functions(*names: str, **bindings: Any) -> dict[str, Any]:
    lines = APP.read_text(encoding="utf-8").splitlines(keepends=True)
    body = []
    for name in names:
        start = next((index for index, line in enumerate(lines)
                      if re.match(rf"^(?:async )?def {re.escape(name)}\(", line)),
                     None)
        if start is None:
            raise AssertionError(f"app.py function missing: {name}")
        end = next((index for index in range(start + 1, len(lines))
                    if re.match(r"^(?:async )?def |^class |^@", lines[index])),
                   len(lines))
        source = ast.parse("".join(lines[start:end]))
        body.extend(node for node in source.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    scope: dict[str, Any] = {"Any": Any, "time": time, **bindings}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(APP), "exec"),
         scope)
    return scope


class RecordTalkShortageDiagnosis(unittest.TestCase):
    def test_record_entries_bill_their_full_minutes_when_air_mode_is_on(self):
        self.assertEqual(
            talk.entry_demand("record", "record", "live only", talk.MODE_AIR),
            ("track_talk", ""),
        )
        self.assertEqual(
            talk.entry_demand("record", "record", "live only", talk.MODE_OFF),
            ("record", "live only"),
        )
        # The module receives neither a music gain nor a playback state.
        # Thus the two 300s/180s record entries still owe 480s when the
        # listener has paused the record with the music slider at zero.

    def test_planner_sees_a_pair_that_road_and_commission_miss(self):
        record = {
            "id": "song-1",
            "intro": {"text": "An introduction for this record.", "seconds": 10},
            "outro": {"text": "A send-off for this record.", "seconds": 8},
        }
        held = {"song-1": record}
        scope = app_functions(
            "dialogue_stock_items", "road_source", "alt_candidates",
            _LARDER=[], _SHELF={}, _TRACK_TALK=held,
            TRACK_TALK_MAX=54,
            _larder_profile_signature=lambda: "profile",
            dialogue_tint_required=lambda: False,
            track_lookahead=lambda most=0: [{"id": "song-1"}],
            track_talk_pair_ready=lambda row: row is record,
            track_talk_part_ready=lambda side: bool(side and side.get("text")),
        )
        stock = scope["dialogue_stock_items"]("track_talk", include_unready=False)
        self.assertEqual(len(stock), 1)
        self.assertTrue(stock[0]["ready"])
        self.assertTrue(stock[0]["fills_entry"])
        self.assertEqual(scope["road_source"]("track_talk"), [])
        self.assertEqual(scope["alt_candidates"]("track_talk"), [])

    def test_road_supply_counts_exact_ready_pairs_and_partial_bookends(self):
        tracks = [
            {"id": "song-1", "title": "First", "seconds": 180,
             "intro": "ready", "outro": "ready"},
            {"id": "song-2", "title": "Second", "seconds": 240,
             "intro": "", "outro": "written"},
            {"id": "tape-1", "seconds": 60, "tape": True,
             "intro": "ready", "outro": "ready"},
        ]
        scope = app_functions(
            "record_talk_supply", TRACK_TALK_MAX=54,
            track_talk_state=lambda most: {"tracks": tracks},
        )
        supply = scope["record_talk_supply"]()
        self.assertEqual(supply["held_records"], 2)
        self.assertEqual(supply["ready_pairs"], 1)
        self.assertEqual(supply["ready_seconds"], 180)
        self.assertEqual(supply["ready_parts"], 2)
        self.assertEqual(supply["written_parts"], 3)
        self.assertEqual([row["id"] for row in supply["tracks"]],
                         ["song-1", "song-2"])

    def test_road_explains_a_written_bookend_waiting_for_voice(self):
        scope = app_functions("_coord_road_doing", _BRIEF_LOG=[],
                              _RENDER_BACKLOG=[])
        report = {"road": "track_talk", "label": "record talk",
                  "record_talk": {"tracks": [
                      {"title": "Second", "intro": "", "outro": "written"}]},
                  "shelf": {"full": False}, "owes": {}, "plan": {}}
        lines = scope["_coord_road_doing"](report)
        self.assertTrue(any("Second" in line["text"]
                            and "outro" in line["text"]
                            and "durable voice take" in line["text"]
                            for line in lines))

    def test_empty_music_queue_is_reported_full_to_prep(self):
        scope = app_functions(
            "track_talk_full", "track_talk_need",
            track_talk_on=lambda: True,
            track_lookahead=lambda: [],
        )
        self.assertTrue(scope["track_talk_full"]())
        self.assertEqual(scope["track_talk_need"](), 0.0)
        # This is not the live cause: the observed queue currently has
        # dozens of tracks. It is a separate empty-queue failure mode.


if __name__ == "__main__":
    unittest.main()
