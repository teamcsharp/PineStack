import unittest

from orchestrator_rooms import schedule_cupboard_handoff


def slot(road, due, *, short=0, written=0, items=None, state="partial"):
    return {"road": road, "label": road, "in_seconds": due,
            "commit_id": f"{road}@{due}", "owns_seconds": 240,
            "short_seconds": short, "written_only_seconds": written,
            "state": state, "items": items or []}


def written_item(ident, lines=2):
    return {"id": ident, "sid": ident, "ready": False,
            "allocated_seconds": 120, "counts": {"written": lines}}


def handoff(slots, *, full=False, available=True):
    return schedule_cupboard_handoff(
        {"available": available, "slots": slots},
        {"ad", "news", "gallery"}, lambda road: full)


class ScheduleCupboardHandoffTests(unittest.TestCase):
    def test_on_air_shortfall_does_not_displace_future_writing(self):
        current = slot("caller", 0, short=70, written=60,
                       items=[written_item("caller-written")])
        current["current"] = True
        result = schedule_cupboard_handoff(
            {"available": True, "slots": [
                current,
                slot("recap", 500, short=70, state="missing"),
                slot("caller", 2100, short=180, state="missing"),
            ]}, {"caller", "recap"}, lambda road: False)
        self.assertEqual([(row["road"], row["due_in"])
                          for row in result["write"]],
                         [("recap", 500), ("caller", 2100)])
        self.assertEqual(result["write"][1]["want_seconds"], 180)
        self.assertEqual(result["record"][0]["item_id"], "caller-written")

    def test_earliest_bound_work_beats_later_missing_airtime(self):
        result = handoff([
            slot("ad", 900, short=240, state="missing"),
            slot("news", 120, written=120, items=[written_item("bulletin")]),
            slot("gallery", 300, short=240, state="missing"),
        ])
        self.assertEqual([(r["action"], r["road"]) for r in result["work"]],
                         [("record", "news"), ("write", "gallery"),
                          ("write", "ad")])
        self.assertEqual(result["record"][0]["item_id"], "bulletin")

    def test_missing_road_survives_aggregate_cover_and_written_rows_dedupe(self):
        result = handoff([
            slot("ad", 60, written=120, items=[written_item("ad-1")]),
            slot("ad", 240, short=240, written=120,
                 items=[written_item("ad-1")]),
            slot("ad", 600, short=120, state="missing"),
        ])
        self.assertEqual(len(result["record"]), 1)
        self.assertEqual(len(result["write"]), 1)
        self.assertEqual(result["write"][0]["want_seconds"], 360)
        self.assertEqual(result["write"][0]["due_in"], 240)
        self.assertEqual(result["work"][0]["action"], "record")

    def test_short_authored_script_is_commissioned_despite_full_allocation(self):
        draft = slot("ad", 180, written=240,
                     items=[written_item("thin-ad")])
        draft["ready_seconds"] = 0.0
        draft["coverage"] = {"script_short_seconds": 150.0}
        result = handoff([draft])
        self.assertEqual(result["write"][0]["want_seconds"], 150.0)
        self.assertEqual(result["write"][0]["commit_id"], "ad@180")
        self.assertEqual(result["record"][0]["item_id"], "thin-ad")

    def test_measured_short_body_commissions_more_speech(self):
        produced = slot("gallery", 180, items=[{"id": "round", "ready": True}])
        produced["ready_seconds"] = 240.0
        produced["contract"] = {"speech_seconds": 240.0}
        produced["coverage"] = {"playable_seconds": 43.0,
                                "duration_short_seconds": 196.0}
        result = handoff([produced])
        self.assertEqual(result["write"][0]["want_seconds"], 196.0)

    def test_full_audio_with_missing_dialogue_turns_commissions_structure(self):
        prepared = slot("gallery", 180, items=[{"id": "round", "ready": True}])
        prepared["ready_seconds"] = 240.0
        prepared["coverage"] = {"playable_seconds": 240.0,
                                "writing_structure_short_seconds": 24.0}
        result = handoff([prepared])
        self.assertEqual(result["write"][0]["want_seconds"], 24.0)

    def test_full_shelf_structural_debt_targets_one_bound_round(self):
        prepared = slot("gallery", 180, items=[
            {"id": "g-small", "sid": "g-small", "ready": True, "round": True,
             "allocated_seconds": 60, "lines": [{"text": "A pitch"}]},
            {"id": "g-main", "sid": "g-main", "ready": True, "round": True,
             "allocated_seconds": 180, "lines": [{"text": "A larger pitch"}]},
        ])
        prepared["ready_seconds"] = 240.0
        prepared["coverage"] = {"playable_seconds": 240.0,
                                "writing_structure_short_seconds": 24.0,
                                "missing_turns": 11}
        result = handoff([prepared], full=True)
        self.assertEqual(result["write"], [])
        self.assertEqual(result["blocked"], [])
        self.assertEqual(len(result["quality"]), 1)
        self.assertEqual(result["quality"][0]["item_id"], "g-main")
        self.assertEqual(result["quality"][0]["add_turns"], 11)
        self.assertEqual(result["work"][0]["action"], "quality")

    def test_full_shelf_speech_debt_expands_bound_news_in_place(self):
        prepared = slot("news", 180, items=[
            {"id": "news-small", "sid": "news-small", "ready": True,
             "round": True, "seconds": 30, "allocated_seconds": 30,
             "lines": [{"text": "First"}] * 4},
            {"id": "news-main", "sid": "news-main", "ready": True,
             "round": True, "seconds": 78, "allocated_seconds": 78,
             "lines": [{"text": "Second"}] * 12},
        ])
        prepared["owns_seconds"] = 180
        prepared["ready_seconds"] = 180
        prepared["coverage"] = {
            "playable_seconds": 160,
            "duration_short_seconds": 20,
            "script_short_seconds": 0,
            "recording_short_seconds": 6,
            "writing_structure_short_seconds": 0,
        }
        result = handoff([prepared], full=True)
        self.assertEqual(result["write"], [])
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["quality_waiting"], 1)
        self.assertEqual(result["quality"][0]["item_id"], "news-main")
        self.assertEqual(result["quality"][0]["body_short_seconds"], 20)
        self.assertEqual(result["quality"][0]["speech_short_seconds"], 6)
        self.assertEqual(result["quality"][0]["add_turns"], 4)
        open_shelf = handoff([prepared], full=False)
        self.assertEqual(open_shelf["write"], [])
        self.assertEqual(open_shelf["quality"][0]["item_id"], "news-main")

        uncovered = slot("news", 900, short=180, state="missing")
        mixed = handoff([prepared, uncovered], full=False)
        self.assertEqual(mixed["quality"][0]["item_id"], "news-main")
        self.assertEqual(mixed["write"][0]["commit_id"], "news@900")

    def test_full_single_read_has_no_quality_rewrite(self):
        prepared = slot("ad", 180, items=[
            {"id": "ad-1", "sid": "ad-1", "ready": True,
             "round": False, "allocated_seconds": 240}])
        prepared["ready_seconds"] = 240.0
        prepared["coverage"] = {"writing_structure_short_seconds": 24.0}
        result = handoff([prepared], full=True)
        self.assertEqual(result["quality"], [])
        self.assertEqual(result["blocked"][0]["road"], "ad")

    def test_recap_does_not_take_dialogue_quality_path(self):
        prepared = slot("recap", 180, items=[
            {"id": "recap-1", "sid": "recap-1", "ready": True,
             "round": True, "allocated_seconds": 240}])
        prepared["ready_seconds"] = 240.0
        prepared["coverage"] = {"writing_structure_short_seconds": 24.0}
        result = schedule_cupboard_handoff(
            {"available": True, "slots": [prepared]}, {"recap"}, lambda _: True)
        self.assertEqual(result["quality"], [])

    def test_incomplete_record_bookend_is_sent_to_recording_room(self):
        record = slot("track_talk", 180, items=[{
            "id": "track_talk:record-1", "ready": False,
            "counts": {"written": 0},
            "lines": [{"part": "intro", "state": "rendered"},
                      {"part": "outro", "state": "missing"}]}])
        result = schedule_cupboard_handoff(
            {"available": True, "slots": [record]}, {"track_talk"}, lambda _: False)
        self.assertEqual(result["record"][0]["item_id"], "track_talk:record-1")
        self.assertEqual(result["record"][0]["bookends"], ["outro"])

    def test_shelf_gate_and_ticket_limits_are_reported(self):
        slots = [slot(road, i * 60, short=240, state="missing")
                 for i, road in enumerate(("ad", "news", "gallery"))]
        result = schedule_cupboard_handoff(
            {"available": True, "slots": slots},
            {"ad", "news", "gallery"}, lambda road: road == "news",
            write_most=1)
        self.assertEqual([r["road"] for r in result["write"]], ["ad"])
        self.assertEqual(result["write_waiting"], 2)
        self.assertEqual(result["blocked"][0]["road"], "news")
        self.assertTrue(result["truncated"])

    def test_unknown_or_outside_bank_creates_no_orders(self):
        rows = [slot("ad", 3601, short=240),
                slot("news", 300, written=120,
                     items=[{"id": "ready", "ready": True,
                             "counts": {"written": 2}}])]
        self.assertEqual(handoff(rows)["work"], [])
        self.assertFalse(handoff(rows, available=False)["available"])
        self.assertEqual(schedule_cupboard_handoff(
            {"available": True, "slots": [slot("ad", 0, short=240)]},
            {"ad"}, lambda road: False, horizon_seconds=0)["work"], [])

    def test_same_deadline_finishes_written_stock_first_and_caps_records(self):
        items = [written_item(f"item-{i}") for i in range(8)]
        result = handoff([slot("ad", 0, short=240, written=120,
                               items=items)])
        self.assertEqual(result["work"][0]["action"], "record")
        self.assertEqual(result["work"][-1]["action"], "write")
        self.assertEqual(result["record_waiting"], 8)
        self.assertEqual(len(result["record"]), 6)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
