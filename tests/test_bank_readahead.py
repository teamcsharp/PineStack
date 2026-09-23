"""Read-ahead production queue boundary tests."""
import unittest
from types import SimpleNamespace

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
        bank._MEMO.update(at=0.0, minutes=0, value=None)

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


if __name__ == "__main__":
    unittest.main()
