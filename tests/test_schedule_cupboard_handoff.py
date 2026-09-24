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
