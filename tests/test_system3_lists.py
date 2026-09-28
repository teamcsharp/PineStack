"""[s3-lists] Every list that feeds the air is an editable table on System 3's
desk: the registry (system3_lists.py) and the SFX Guy's speech bank's desk
doors (sfx_speech_bank.py). Pure - no app import; the app's wiring is
StationTests at the end, which runs only where app.py imports (the
station's container)."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

import system3_lists
from system3_lists import ListError, ListRegistry
from sfx_speech_bank import SfxSpeechBank, line_key


class BankDesk(unittest.TestCase):
    V, P = "drop-one", "crystal-one"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = [1000.0]
        self.bank = SfxSpeechBank(self.root / "bank.json", self.root, clock=lambda: self.now[0])

    def fresh(self):
        """The same files, a new process: nothing held in memory."""
        return SfxSpeechBank(self.root / "bank.json", self.root, clock=lambda: self.now[0])

    def record(self, text, profile=None, plays=0):
        """Seed and 'record' one line the way the preparation loop leaves it."""
        profile = profile or self.P
        self.bank.seed(self.V, profile, [{"text": text, "generic": True}])
        row = next(r for r in self.bank.rows(self.V, profile) if r["text_plain"] == text)
        name = row["id"] + ".wav"
        (self.root / name).write_bytes(b"a real fixture file")
        row.update(state="ready", clip={"path": "/media/" + name, "seconds": 3}, recorded_text=text,
                   recorded_voice=self.V, key="k-" + row["id"], engine="xtts", seconds=3,
                   why="Whole rhymed line recorded in the SFX speaker's voice")
        self.bank.put(row)
        if plays:
            stored = dict(self.bank._load())
            stored[row["id"]] = {**stored[row["id"]], "plays": plays, "last_played": 500.0}
            self.bank._save(stored)
        return row

    def line(self, text):
        return self.bank.desk_line(line_key(text), self.V, self.P)

    def pickable(self):
        got = self.bank.eligible("", self.V, self.P, lambda row: True)
        return {r["text"] for r in got}

    # --- what the desk shows ------------------------------------------------
    def test_a_line_is_every_take_of_its_words(self):
        self.record("I sold the tapes to Sawyer.", plays=65)
        self.record("I sold the tapes to Sawyer.", profile="older-crystal", plays=23)
        self.record("Keep talking.")
        rows = self.bank.desk_rows(self.V, self.P)
        self.assertEqual(len(rows), 2)
        sawyer = self.line("I sold the tapes to Sawyer.")
        self.assertEqual((sawyer["state"], sawyer["on"], sawyer["plays"], sawyer["takes"], sawyer["current"]),
                         ("ready", True, 88, 2, 1))
        self.assertEqual(sawyer["last_played"], 500.0)
        self.assertEqual(rows[0]["text"], "I sold the tapes to Sawyer.", "the most heard first")

    def test_a_take_under_another_profile_only_is_dormant(self):
        self.record("Only under the old crystal.", profile="older-crystal")
        self.assertEqual(self.line("Only under the old crystal.")["state"], "dormant")

    # --- edit ---------------------------------------------------------------
    def test_an_edit_throws_the_recording_away_and_queues_the_new_words(self):
        old = self.record("I sold the tapes to Sawyer.", plays=65)
        self.assertIn("I sold the tapes to Sawyer.", self.pickable())
        new_id = self.bank.desk_edit(line_key("I sold the tapes to Sawyer."), "I gave the tapes to Sawyer.")
        self.assertEqual(new_id, line_key("I gave the tapes to Sawyer."))
        row = self.fresh().rows()[0]
        self.assertEqual(row["id"], old["id"], "the take keeps its key")
        self.assertEqual((row["text"], row["text_plain"], row["state"]),
                         ("I gave the tapes to Sawyer.", "I gave the tapes to Sawyer.", "waiting"))
        for gone in ("clip", "recorded_text", "recorded_voice", "key", "engine", "seconds", "plays", "last_played"):
            self.assertNotIn(gone, row)
        self.assertEqual(row["plays_before_edit"], 65)
        self.assertEqual(self.pickable(), set(), "nothing of the old words airs")
        self.assertEqual([r["id"] for r in self.bank.due(self.V, self.P)], [old["id"]],
                         "the preparation loop records it again")
        self.assertEqual(self.bank.protected_files(), set(), "the old recording is no longer kept")

    def test_the_station_source_does_not_come_back_after_an_edit(self):
        self.record("I sold the tapes to Sawyer.")
        self.bank.desk_edit(line_key("I sold the tapes to Sawyer."), "I gave the tapes to Sawyer.")
        bank = self.fresh()
        self.assertEqual(bank.seed(self.V, self.P, [{"text": "I sold the tapes to Sawyer.", "generic": True}]), 0)
        self.assertEqual([r["text"] for r in bank.rows()], ["I gave the tapes to Sawyer."])
        # a new Crystal profile seeds every source again - as the rewrite
        self.assertEqual(bank.seed(self.V, "new-crystal", [{"text": "I sold the tapes to Sawyer."}]), 1)
        self.assertEqual({r["text"] for r in bank.rows(self.V, "new-crystal")}, {"I gave the tapes to Sawyer."})

    def test_an_edit_refuses_an_inflight_preparation_of_the_old_words(self):
        self.bank.seed(self.V, self.P, [{"text": "Old words."}])
        inflight = self.bank.due(self.V, self.P)[0]
        self.bank.desk_edit(line_key("Old words."), "New words.")
        inflight.update(state="ready", recorded_text="Old words.", clip={"path": "/media/x.wav", "seconds": 2})
        with self.assertRaises(ValueError):
            self.bank.put(inflight)
        self.assertEqual(self.bank.rows()[0]["text"], "New words.")

    def test_an_edit_onto_words_already_banked_is_refused(self):
        self.record("One.")
        self.record("Two.")
        with self.assertRaises(ValueError):
            self.bank.desk_edit(line_key("One."), "two.")

    # --- add ----------------------------------------------------------------
    def test_an_added_line_is_queued_to_be_recorded(self):
        new_id = self.bank.desk_add("Brand new line from the desk.", self.V, self.P)
        got = self.bank.desk_line(new_id, self.V, self.P)
        self.assertEqual((got["state"], got["origin"], got["on"]), ("waiting", "desk", True))
        self.assertEqual([r["text"] for r in self.bank.due(self.V, self.P)], ["Brand new line from the desk."])
        with self.assertRaises(ValueError):
            self.bank.desk_add("brand new  line from the desk.", self.V, self.P)

    def test_an_added_line_without_a_voice_waits_and_is_a_source_for_every_profile(self):
        new_id = self.bank.desk_add("Said once the speaker is on.")
        self.assertEqual(self.bank.desk_line(new_id)["state"], "queued")
        bank = self.fresh()
        self.assertEqual(bank.seed(self.V, self.P, []), 1)
        self.assertEqual(bank.desk_line(new_id, self.V, self.P)["state"], "waiting")
        self.assertEqual(bank.seed(self.V, "new-crystal", []), 1)

    # --- remove -------------------------------------------------------------
    def test_a_removal_is_real_and_survives_the_seed(self):
        self.record("I sold the tapes to Sawyer.")
        self.record("I sold the tapes to Sawyer.", profile="older-crystal")
        self.assertEqual(self.bank.desk_remove(line_key("I sold the tapes to Sawyer.")), 2)
        self.assertEqual(self.bank.rows(), [])
        self.assertEqual(self.bank.protected_files(), set())
        bank = self.fresh()
        for profile in (self.P, "older-crystal", "new-crystal"):
            self.assertEqual(bank.seed(self.V, profile, [{"text": "I sold the tapes to Sawyer."},
                                                         {"text": "i sold  the tapes to sawyer."}]), 0)
        self.assertEqual(bank.rows(), [])
        with self.assertRaises(KeyError):
            bank.desk_remove(line_key("I sold the tapes to Sawyer."))

    def test_removing_an_edited_line_tombstones_its_old_words_too(self):
        self.record("Old words.")
        self.bank.desk_edit(line_key("Old words."), "New words.")
        self.bank.desk_remove(line_key("New words."))
        self.assertEqual(self.fresh().seed(self.V, self.P, [{"text": "Old words."}, {"text": "New words."}]), 0)

    def test_adding_removed_words_back_brings_them_back(self):
        self.record("Back again.")
        self.bank.desk_remove(line_key("Back again."))
        self.bank.desk_add("Back again.", self.V, self.P)
        self.assertEqual(self.line("Back again.")["state"], "waiting")

    # --- switch -------------------------------------------------------------
    def test_a_line_switched_off_is_never_picked_nor_recorded(self):
        self.record("Switch me off.")
        self.record("Leave me on.")
        self.bank.desk_switch(line_key("Switch me off."), False)
        self.assertEqual(self.pickable(), {"Leave me on."})
        for _ in range(5):
            got = self.bank.pick("switch me off", self.V, self.P, lambda row: True, cooldown=0)
            self.assertEqual(got["text"], "Leave me on.")
            self.bank.finish(got["id"], heard=False)
        self.assertEqual(self.line("Switch me off.")["state"], "off")
        # a later seed under a new profile arrives off, and it is not recorded
        bank = self.fresh()
        bank.seed(self.V, "new-crystal", [{"text": "Switch me off."}])
        self.assertTrue(bank.rows(self.V, "new-crystal")[0].get("off"))
        self.assertEqual(bank.due(self.V, "new-crystal"), [])
        # the preparation's own write cannot switch it back on
        row = bank.rows(self.V, self.P, deep=False)
        stale = next(dict(r) for r in row if r["text"] == "Switch me off.")
        stale.pop("off")
        bank.put(stale)
        self.assertTrue(next(r for r in bank.rows(self.V, self.P) if r["text"] == "Switch me off.")["off"])
        bank.desk_switch(line_key("Switch me off."), True)
        self.assertIn("Switch me off.", {r["text"] for r in bank.eligible("", self.V, self.P, lambda r: True)})

    def test_a_ledger_that_cannot_be_saved_leaves_the_desk_as_it_was(self):
        self.record("Stays.")
        desk_before = self.bank._desk_path().read_text() if self.bank._desk_path().exists() else None
        with mock.patch.object(self.bank, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.bank.desk_remove(line_key("Stays."))
        self.assertEqual(len(self.fresh().rows()), 1)
        after = self.bank._desk_path().read_text() if self.bank._desk_path().exists() else None
        self.assertEqual(json.loads(after)["removed"] if after else {}, json.loads(desk_before)["removed"] if desk_before else {})
        self.assertEqual(self.fresh().seed(self.V, "new-crystal", [{"text": "Stays."}]), 1)


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "edits.jsonl"
        self.now = [100.0]
        self.reg = ListRegistry(self.path, clock=lambda: self.now.__setitem__(0, self.now[0] + 1) or self.now[0])
        self.words = ["alpha one", "beta two", "gamma three"]

        def rows():
            return [{"id": system3_lists.text_id(w), "text": w, "on": True} for w in self.words]

        def add(body):
            w = system3_lists.clean_words(body.get("text"))
            if w in self.words:
                raise ValueError("already there")
            self.words.append(w)
            return system3_lists.text_id(w)

        def edit(rid, body):
            at = [system3_lists.text_id(w) for w in self.words].index(rid)
            self.words[at] = system3_lists.clean_words(body.get("text"))
            return system3_lists.text_id(self.words[at])

        def remove(rid):
            at = [system3_lists.text_id(w) for w in self.words].index(rid)
            return self.words.pop(at)

        self.reg.register({"id": "demo", "label": "Demo", "family": "LIST", "what": "words", "rows": rows,
                           "add": add, "edit": edit, "remove": remove})

    def test_catalog_counts_and_says_what_each_list_can_take(self):
        got = self.reg.catalog()
        self.assertEqual(got[0]["count"], 3)
        self.assertEqual(got[0]["can"], {"add": True, "edit": True, "switch": False, "remove": True})

    def test_a_broken_store_does_not_blank_the_catalog(self):
        self.reg.register({"id": "broken", "family": "LIST", "rows": lambda: 1 / 0})
        got = {c["id"]: c for c in self.reg.catalog()}
        self.assertEqual(got["demo"]["count"], 3)
        self.assertIn("ZeroDivisionError", got["broken"]["error"])

    def test_page_search_and_bounds(self):
        got = self.reg.page("demo", q="BETA")
        self.assertEqual([r["text"] for r in got["rows"]], ["beta two"])
        got = self.reg.page("demo", offset=1, limit=1)
        self.assertEqual((got["total"], [r["text"] for r in got["rows"]]), (3, ["beta two"]))
        self.assertEqual(self.reg.page("demo", limit=10 ** 6)["limit"], system3_lists.MAX_LIMIT)
        with self.assertRaises(ListError) as caught:
            self.reg.page("nope")
        self.assertEqual(caught.exception.status, 404)

    def test_every_write_is_recorded_before_the_store_and_failures_after(self):
        who = system3_lists.who_of("10.89.1.20", "Mozilla/5.0 Electron/30")
        got = self.reg.add("demo", {"text": "delta four"}, who)
        self.assertEqual(got["row"]["text"], "delta four")
        with self.assertRaises(ListError) as caught:
            self.reg.add("demo", {"text": "delta four"}, who)
        self.assertEqual(caught.exception.status, 400)
        moved = self.reg.edit("demo", system3_lists.text_id("alpha one"), {"text": "alpha uno"}, who)
        self.assertEqual(moved["id"], system3_lists.text_id("alpha uno"))
        self.reg.remove("demo", system3_lists.text_id("gamma three"), who)
        edits = self.reg.edits("demo")
        self.assertEqual([e["op"] for e in edits], ["remove", "edit", "add", "add"])
        self.assertEqual(edits[0]["before"]["text"], "gamma three")
        self.assertEqual(edits[1]["asked"], {"text": "alpha uno"})
        self.assertEqual(edits[2]["failed"], "already there")
        self.assertNotIn("failed", edits[3])
        self.assertEqual(edits[0]["who"]["what"], "the desktop app")
        self.assertEqual(len(self.path.read_text().splitlines()), 5, "four attempts and one failure")

    def test_doors_a_list_lacks_answer_405_and_unknown_rows_404(self):
        with self.assertRaises(ListError) as caught:
            self.reg.edit("demo", system3_lists.text_id("beta two"), {"on": False})
        self.assertEqual(caught.exception.status, 405)
        with self.assertRaises(ListError) as caught:
            self.reg.remove("demo", "0000")
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(ListError) as caught:
            self.reg.edit("demo", system3_lists.text_id("beta two"), {})
        self.assertEqual(caught.exception.status, 400)

    def test_the_bank_through_the_registry(self):
        root = Path(self.tmp.name)
        bank = SfxSpeechBank(root / "bank.json", root)
        bank.seed("v", "p", [{"text": "I sold the tapes to Sawyer."}])
        self.reg.register({"id": "sfxguy.bank", "family": "BANK", "rows": lambda: bank.desk_rows("v", "p"),
                           "add": lambda body: bank.desk_add(body.get("text"), "v", "p"),
                           "edit": lambda rid, body: bank.desk_edit(rid, body.get("text")),
                           "switch": lambda rid, on: bank.desk_switch(rid, on),
                           "remove": bank.desk_remove})
        rid = line_key("I sold the tapes to Sawyer.")
        got = self.reg.edit("sfxguy.bank", rid, {"text": "I kept the tapes.", "on": False})
        self.assertEqual((got["row"]["text"], got["row"]["state"], got["row"]["on"]), ("I kept the tapes.", "off", False))
        with self.assertRaises(ListError) as caught:
            self.reg.edit("sfxguy.bank", "feedface", {"text": "x"})
        self.assertEqual(caught.exception.status, 404)
        self.reg.remove("sfxguy.bank", got["id"])
        self.assertEqual(self.reg.page("sfxguy.bank")["total"], 0)


class StationTests(unittest.TestCase):
    """The app's wiring - runs only where app.py imports (the container)."""

    @classmethod
    def setUpClass(cls):
        try:
            import app  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest("app.py imports only in the station's container: %s" % exc)

    def test_the_speech_bank_is_registered_first_with_every_door(self):
        import app
        first = next(iter(app._S3_LISTS.lists.values()))
        self.assertEqual((first["id"], first["family"]), ("sfxguy.bank", "BANK"))
        meta = app._S3_LISTS.meta(first)
        self.assertEqual(meta["can"], {"add": True, "edit": True, "switch": True, "remove": True})

    def test_routes_exist(self):
        import app
        paths = {(getattr(r, "path", ""), m) for r in app.app.routes for m in (getattr(r, "methods", None) or ())}
        for want in (("/api/system3/lists", "GET"), ("/api/system3/lists/{list_id}", "GET"),
                     ("/api/system3/lists/{list_id}/rows", "POST"),
                     ("/api/system3/lists/{list_id}/rows/{row_id}", "PUT"),
                     ("/api/system3/lists/{list_id}/rows/{row_id}", "DELETE")):
            self.assertIn(want, paths)

    def test_the_bank_rows_use_the_voice_and_profile_on_air(self):
        import app
        with mock.patch.object(app, "dj_settings", lambda: {"drop_voice": "v"}), \
                mock.patch.object(app, "_sfxguy_ready_profile", lambda: "p"), \
                mock.patch.object(app._SFX_READY_BANK, "desk_rows", side_effect=lambda v, p: [{"id": v + p, "text": ""}]):
            self.assertEqual(app._S3_LISTS.spec("sfxguy.bank")["rows"](), [{"id": "vp", "text": ""}])


if __name__ == "__main__":
    unittest.main()
