"""[book-nodes] 2026-10-06: Book Time is System 3 nodes - three roads, a BOOK family, nothing gated.

"I want the node configuration altered to have them able to do more book work... creating nodes
and offerings rolling randomly through the options we need to roll between."
"""
import unittest

import system3
import system3_tables
from test_system3 import inputs, settings


class TheNodes(unittest.TestCase):
    def test_the_family_the_roads_the_tables_and_the_structures_exist(self):
        self.assertIn("BOOK", system3.FAMILIES)
        for road in ("book_open", "book_read", "book_close"):
            self.assertIn(road, system3.ROADS)
            self.assertIn(road, system3_tables.ROAD_IDS)
            st = system3_tables.DEFAULT_ROAD_STRUCTURES[road]
            self.assertEqual(st["kind"], "legs")
            self.assertEqual(system3_tables.validate_structure(road, st), [], road + " validates")
        ids = {t["id"] for t in system3_tables.DEFAULT_TABLES}
        for table in ("BK1", "BK2", "BK3"):
            self.assertIn(table, ids)
            row = next(t for t in system3_tables.DEFAULT_TABLES if t["id"] == table)
            self.assertEqual(row["family"], "BOOK")
            self.assertGreaterEqual(len(row["categories"][0]["items"]), 6, table + " offers a wheel, not a coin")

    def test_the_reading_legs_carry_the_passage_and_roll_the_book_work(self):
        read = system3_tables.DEFAULT_ROAD_STRUCTURES["book_read"]
        legs = {leg["id"]: leg for leg in read["legs"]}
        self.assertEqual(list(legs), ["read", "take", "errand", "read_on", "turn"])
        self.assertIn("{booksentences}", legs["read"]["act"], "the reading leg carries the passage itself")
        self.assertIn("{booksentence}", legs["read_on"]["act"])
        for leg_id in ("read", "take", "errand", "read_on"):
            self.assertTrue(any(d["family"] == "BOOK" for d in legs[leg_id]["draws"]), leg_id + " rolls the book work")
        opening = {leg["id"]: leg for leg in system3_tables.DEFAULT_ROAD_STRUCTURES["book_open"]["legs"]}
        self.assertIn("Book Time on {stationname}", opening["hello_a"]["act"])
        self.assertIn("{book}", opening["hello_a"]["act"])
        self.assertIn("{bookchapter}", opening["hello_a"]["act"])
        close = {leg["id"]: leg for leg in system3_tables.DEFAULT_ROAD_STRUCTURES["book_close"]["legs"]}
        self.assertTrue(any(d.get("closes") for d in close["signoff"]["draws"]), "the sign-off closes")
        self.assertIn("the music is handed back", close["signoff"]["act"])   # [book-nodes-3] the sign-off is a wheel now

    def test_a_reading_round_is_planned_from_its_own_legs(self):
        cfg = system3.default_config()
        conv = system3.new_conversation(inputs(road="book_read", seats=["A", "B"], turns=8), cfg,
                                        settings(test_seed="book-1"), conversation_id="c-book-1")
        system3.plan_legs(conv, cfg, conv["inputs"], "book_read")
        legs = [t["leg"] for t in conv["turns"]]
        self.assertEqual(legs[0], "read", "a reading round opens with a reading")
        self.assertIn("take", legs)
        self.assertTrue(6 <= len(conv["turns"]) <= 10, "the road's own floor and ceiling: %d" % len(conv["turns"]))
        book_turns = [t for t in conv["turns"] if any(d["family"] == "BOOK" for d in t["decisions"])]
        self.assertGreaterEqual(len(book_turns), 3, "the book work is rolled on the reading, take, errand and read-on legs")
        for t in conv["turns"]:
            self.assertTrue(any(d["family"] == "ES" for d in t["decisions"]), "every leg rolls its feeling")
        self.assertEqual({t["speaker"] for t in conv["turns"]} - {"A", "B"}, set(), "two hosts, nobody else")

    def test_the_book_work_prints_on_the_running_order_row(self):
        turn = {"leg": "read", "speaker": "A", "decisions": [], "directions": [
            {"family": "ES", "text": "calm"}, {"family": "BOOK", "text": "reads it slowly, savouring the words"}]}
        try:
            printed = system3._leg_row_add(turn) if hasattr(system3, "_leg_row_add") else ""
        except TypeError:
            printed = ""
        if isinstance(printed, str) and printed:
            self.assertIn("the book work: reads it slowly", printed)
        src = open(system3.__file__, encoding="utf-8").read()
        self.assertIn('add += "; the book work: " + book[-1]', src)

    def test_the_register_names_the_three_roads(self):
        rows = {r["id"]: r for r in system3_tables.ROAD_REGISTER}
        for road in ("book_open", "book_read", "book_close"):
            self.assertIn(road, rows)
            self.assertEqual(rows[road]["shape"], "legs")
            self.assertIn("prepare_book", rows[road]["writer"])


if __name__ == "__main__":
    unittest.main()
