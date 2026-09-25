import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from line_blacklist import Blacklist


class BlacklistTests(unittest.TestCase):
    def setUp(self):
        self.room = tempfile.TemporaryDirectory()
        self.addCleanup(self.room.cleanup)
        self.path = Path(self.room.name) / "nested" / "blacklist.json"
        self.blacklist = Blacklist(self.path)

    def test_whole_line_normalization_without_fuzzy_matches(self):
        self.blacklist.add("  Don't stop, at 5!  ", "line-1")
        for text in ("dont STOP at 5", "Don't\nstop -- at 5?", "DON'T stop at 5."):
            with self.subTest(text=text):
                self.assertTrue(self.blacklist.contains(text))
        for text in ("stop at 5", "dont stop at 6", "dont stop at 5 today",
                     "dont stop at", "don't stop at five", "do not stop at 5"):
            with self.subTest(text=text):
                self.assertFalse(self.blacklist.contains(text))
        self.assertFalse(self.blacklist.contains("..."))

    def test_persists_structured_json_and_preserves_first_entry(self):
        first = self.blacklist.add("Caf\u00e9 is open!", "line-7")
        second = self.blacklist.add("CAF\u00c9 IS OPEN?", "line-8")
        self.assertEqual(first, second)
        self.assertEqual(first["text"], "Caf\u00e9 is open!")
        self.assertEqual(first["line_id"], "line-7")
        self.assertIn("+00:00", first["timestamp"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {
            "caf\u00e9 is open": {key: value for key, value in first.items()
                            if key != "normalized"}
        })
        reopened = Blacklist(self.path)
        self.assertFalse(reopened.contains("cafe is open"))
        self.assertTrue(reopened.contains("caf\u00e9 is open"))
        rows = reopened.rows
        self.assertEqual(rows, [first])
        rows[0]["text"] = "changed"
        self.assertEqual(reopened.rows, [first])

    def test_empty_text_and_damaged_store_do_not_overwrite_existing_file(self):
        with self.assertRaises(ValueError):
            self.blacklist.add("!?", "line-1")
        self.assertFalse(self.path.exists())
        self.path.parent.mkdir(parents=True)
        for contents in ("{bad", "[]", '{"bad": "not a record"}'):
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.blacklist.add("some line", "line-2")
                self.assertEqual(self.path.read_text(encoding="utf-8"), contents)

    def test_replace_failure_keeps_previous_store_and_cleans_temp(self):
        self.blacklist.add("one line", "line-1")
        before = self.path.read_bytes()
        with mock.patch("line_blacklist.os.replace", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                self.blacklist.add("another line", "line-2")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_concurrent_instances_keep_every_add(self):
        stores = [self.blacklist, Blacklist(self.path)]

        def add(index):
            stores[index % 2].add(f"unique line {index}", f"id-{index}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(add, range(20)))
        self.assertEqual(len(self.blacklist.rows), 20)
        for index in range(20):
            self.assertTrue(stores[index % 2].contains(f"unique LINE {index}!"))


if __name__ == "__main__":
    unittest.main()
