"""Read-ahead production queue boundary tests."""
import unittest
from types import SimpleNamespace
from unittest import mock

import bank_readahead as bank


class BankApp:
    _PANTRY = {}
    _BANK_PRODUCER = {}

    @staticmethod
    def dialogue_entry(row):
        if not isinstance(row, dict):
            return None
        entry = row.get("entry")
        if isinstance(entry, dict):
            return entry
        if "script" in row and "prep_kind" in row:
            return row
        return None

    @staticmethod
    def dialogue_audio_ready(kind, row):
        return bool(row.get("produced") or row.get("entry"))

    @staticmethod
    def production_cue_map(entry):
        return dict(entry.get("cue_map") or {})

    @staticmethod
    def alt_sid(kind, row):
        return str(row.get("sid") or "")


def inventory(*items):
    public = [{"id": item["id"], "ready": True, "seconds": 30.0,
               "allocated_seconds": 30.0, "ready_seconds": 30.0}
              for item in items]
    return {
        "selected": items,
        "slots": [{"road": "ad", "label": "Ads", "in_seconds": 10.0,
                   "stock": public}],
    }


class ProductionQueueBoundaryTests(unittest.TestCase):
    def setUp(self):
        bank._REFUSED.clear()
        bank._CONTRACTS.clear()
        bank._MEMO.update(at=0.0, minutes=0, value=None)

    def tearDown(self):
        bank._CONTRACTS.clear()

    def test_produced_single_read_is_visible_but_not_a_round_to_assemble(self):
        ad = {"sid": "ad-one", "produced": "ad-book-id",
              "audio": "finished.wav", "text": "A finished advert"}
        item = {"id": "ad-one", "row": ad,
                # Inventory intentionally exposes the row in this field.
                "entry": ad, "ready": True, "seconds": 30.0}
        plan = inventory(item)

        self.assertEqual(bank.production_queue(BankApp(), plan=plan), [])
        viewed = bank.item_view(BankApp(), "ad", item)
        self.assertFalse(viewed["round"])
        self.assertEqual(viewed["state"], "rendered")

    def test_real_dialogue_entry_still_waits_for_its_measured_cue_map(self):
        entry = {"sid": "banter-one", "script": "HOST: hello",
                 "prep_kind": "banter", "takes": [{"who": "host"}]}
        row = {"sid": "banter-one", "entry": entry}
        item = {"id": "banter-one", "row": row, "entry": entry,
                "ready": True, "seconds": 30.0}
        plan = inventory(item)

        queued = bank.production_queue(BankApp(), plan=plan)
        self.assertEqual([q["sid"] for q in queued], ["banter-one"])
        self.assertTrue(bank.item_view(BankApp(), "banter", item)["round"])

    def test_record_carrier_lists_its_two_bookends(self):
        record = {"intro": {"text": "A: Here is the record.", "key": "intro"},
                  "outro": {"text": "", "key": ""}}
        with mock.patch.object(bank, "_pantry_has", side_effect=lambda _app, key: key == "intro"):
            lines = bank.line_states(BankApp(), "track_talk", record)
        self.assertEqual([(line["part"], line["state"]) for line in lines],
                         [("intro", "rendered"), ("outro", "missing")])
        self.assertEqual([line["who"] for line in lines], ["dj", "cohost"])

    def test_bank_contract_finds_short_words_behind_full_forecast(self):
        entry = {"sid": "one", "prep_kind": "banter",
                 "script": "A: A brief setup. B: A brief reply.", "takes": []}
        row = {"sid": "one", "entry": entry}
        item = {"id": "one", "row": row, "entry": entry,
                "ready": False, "seconds": 0.0}
        plan = {"selected": [item], "slots": [{
            "commit_id": "slot-one", "kind": "banter", "road": "banter",
            "label": "Banter", "in_seconds": 120.0,
            "owns_seconds": 120.0, "planned_seconds": 120.0,
            "ready_seconds": 0.0, "short_seconds": 0.0,
            "stock": [{"id": "one", "allocated_seconds": 120.0,
                       "ready_seconds": 0.0}],
        }]}
        with (mock.patch.object(bank, "_plan", return_value=plan),
              mock.patch.object(bank, "production_queue", return_value=[])):
            got = bank._bank_state_fresh(BankApp(), 60, bank.time.time())
        slot = got["slots"][0]
        self.assertEqual(slot["short_seconds"], 0.0)
        self.assertGreater(slot["coverage"]["script_short_seconds"], 100.0)
        self.assertFalse(slot["coverage"]["ready"])
        self.assertTrue(bank.contract_write_needed("banter"))
        self.assertFalse(bank.contract_write_needed("ad"))
        slot["coverage"]["playable_seconds"] = 120.0
        slot["coverage"]["writing_structure_short_seconds"] = 0.0
        self.assertFalse(bank.contract_write_needed("banter"))
        slot["coverage"]["writing_structure_short_seconds"] = 24.0
        self.assertTrue(bank.contract_write_needed("banter"))

    def test_measured_body_shortfall_outranks_full_ready_allocation(self):
        entry = {"sid": "measured", "prep_kind": "banter",
                 "script": "A: A long scripted segment. B: The second voice answers.",
                 "takes": [], "cue_map": {"derivation": "measured", "cues": [{}]},
                 "production": {"supply": {"measured": True,
                     "scripted_seconds": 120, "recorded_seconds": 43,
                     "playable_seconds": 43, "turns": 15, "events": 15,
                     "roles": ["dj", "cohost"]}}}
        row = {"sid": "measured", "entry": entry}
        item = {"id": "measured", "row": row, "entry": entry,
                "ready": True, "seconds": 120.0}
        plan = {"selected": [item], "slots": [{
            "commit_id": "slot-measured", "kind": "banter", "road": "banter",
            "in_seconds": 120.0, "owns_seconds": 120.0,
            "planned_seconds": 120.0, "ready_seconds": 120.0,
            "short_seconds": 0.0, "stock": [{"id": "measured",
                "allocated_seconds": 120.0, "ready_seconds": 120.0}]}]}
        with (mock.patch.object(bank, "_plan", return_value=plan),
              mock.patch.object(bank, "production_queue", return_value=[])):
            got = bank._bank_state_fresh(BankApp(), 60, bank.time.time())
        coverage = got["slots"][0]["coverage"]
        self.assertEqual(coverage["playable_seconds"], 43.0)
        self.assertGreater(coverage["duration_short_seconds"], 70.0)
        self.assertTrue(bank.contract_write_needed("banter"))


if __name__ == "__main__":
    unittest.main()
