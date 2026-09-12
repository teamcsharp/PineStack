"""2026-09-08 (night): the rhyme dictionary, the deep repertoire, the calls.

Four measured scans of the live station:
 - the writer's landings were `it / now / you / that` because the meaning
   contract's anchor floor demands the source's own words survive, so the
   words left to rhyme on were ordinary radio English. The rule that
   satisfies both gates - keep the source's words in the body, spend the
   crystal on the landings - had never been written in the prompt.
 - `rhyme_options_for` walked a SORTED vocabulary and stopped at forty hits,
   so 70% of every rhyme it offered began with a, b or c.
 - the 400 gold bars (52 minutes of finished rhymed audio) carried 1.2% of
   four days of air while 28 continuity lines carried 19.8%, because
   continuity was tried first; eight lines aired over a hundred times each.
 - 18 of 62 calls that rang on air (29%) never said goodbye, because an
   eleven-turn call was paged 2/4/5 and the air waited for TTS at each
   boundary.
"""
import json
import unittest
from unittest import mock

import app
import crystal_prompts
import pine_rhyme


class TheRhymeDictionary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A small crystal with real DOOM words, real frequencies.
        cls.counts = {
            "mic": 772, "told": 610, "villain": 774, "mask": 390, "slaughter": 60,
            "predators": 12, "doom": 900, "emcee": 40, "spit": 120, "legit": 60,
            "quit": 55, "writ": 12, "grit": 30, "wit": 44, "meditation": 20,
            "intoxication": 14, "reincarnation": 9, "inspiration": 30, "station": 57,
            "gunfight": 12, "dynamite": 18, "kryptonite": 22, "limelight": 10,
            "tonight": 300, "aviator": 8, "gladiator": 9, "terminator": 11,
            "it": 900, "you": 1100, "that": 500, "now": 300, "achoo": 1, "babu": 1,
        }
        import tempfile
        import pathlib
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = str(pathlib.Path(cls.tmp.name) / "rhyme_families.json")
        cls.totals = pine_rhyme.build(cls.counts, cls.path)
        cls.book = pine_rhyme.load(cls.path)

    @classmethod
    def tearDownClass(cls):
        pine_rhyme.forget()
        cls.tmp.cleanup()

    def test_the_families_group_words_the_grader_proves_rhyme(self):
        import crystal_rhyme
        self.assertGreater(self.totals["families"], 5)
        self.assertGreater(self.totals["cmu_known"], 25)
        for fam in self.book.family("spit"):
            members = [m["w"] for m in fam["members"]]
            self.assertIn("spit", members)
            for other in members:
                if other != "spit":
                    with self.subTest(pair=("spit", other)):
                        self.assertEqual(crystal_rhyme.rhymes_with("spit", other), "perfect")

    def test_a_distinctive_crystal_word_leads_and_a_one_off_does_not(self):
        got = self.book.options_for("it", 8)
        self.assertTrue(got)
        self.assertNotIn("achoo", got)
        for word in got:
            with self.subTest(word=word):
                self.assertNotIn(word, pine_rhyme.FUNCTION)
                self.assertNotIn(word, pine_rhyme.FURNITURE)
        # the crystal's own distinctive words are what it reaches for
        self.assertTrue({"spit", "legit", "quit", "grit", "wit"} & set(got))

    def test_the_multisyllabic_families_are_found(self):
        self.assertGreaterEqual(self.totals["multisyllabic_families"], 3)
        got = self.book.options_for("station", 8)
        self.assertTrue({"meditation", "intoxication", "reincarnation", "inspiration"} & set(got))

    def test_the_live_vocabulary_is_the_authority_on_membership(self):
        # A crystal that is on with sixteen words may only be offered those.
        small = frozenset({"spit", "legit", "grit"})
        got = self.book.options_for("it", 8, vocab=small)
        self.assertTrue(got)
        self.assertTrue(set(got) <= small)
        # ...and a word the live set has that the artifact lacks still works
        other = frozenset({"skit", "flit"})
        self.assertTrue(set(self.book.options_for("it", 8, vocab=other)) <= other)

    def test_a_landing_pair_keeps_a_word_the_source_already_said(self):
        source = "He had to spit about the whole station"
        pairs = self.book.landing_pairs(source, want=4)
        self.assertTrue(pairs)
        anchored = [p for p in pairs if p["kind"] == "anchored"]
        self.assertTrue(anchored, pairs)
        for row in anchored:
            with self.subTest(pair=row["pair"]):
                self.assertIn(row["pair"][0], source.lower())
                self.assertNotIn(row["pair"][1], source.lower())

    def test_the_open_pairs_are_the_crystals_own_couplets(self):
        # A source with nothing the crystal can answer still gets pairs, and
        # they are multisyllabic families out of the crystal itself.
        pairs = self.book.landing_pairs("Zqx wug blorf", want=3)
        self.assertTrue(pairs)
        self.assertTrue(all(p["kind"] == "open" for p in pairs), pairs)
        self.assertTrue(all(p["tail_nuclei"] >= 2 for p in pairs), pairs)

    def test_one_stem_is_not_a_pair(self):
        for word in self.book.options_for("told", 8):
            self.assertNotEqual(word, "told")
            self.assertFalse(word.startswith("told"))

    def test_the_prompt_block_renders_and_says_what_it_is(self):
        pairs = self.book.landing_pairs("The villain told the mic a story", want=3)
        block = crystal_prompts.crystal_landings(pairs, {"villain": ["chillin"]})
        self.assertTrue(block)
        self.assertIn("pairs", block)
        self.assertIn("Decide the landing words first", block["use"])
        text = json.dumps(block)
        self.assertNotIn("fm", json.loads(text).get("partners", {}))
        self.assertIsNone(crystal_prompts.crystal_landings([], {}))

    def test_the_options_fall_back_when_the_artifact_is_absent(self):
        with mock.patch.object(app, "RHYME_FAMILIES_PATH", "/nonexistent/rhyme_families.json"), \
                mock.patch.object(app, "_crystal_vocab", lambda: frozenset({"spit", "legit"})), \
                mock.patch.object(app, "_RHYME_OPTIONS_MEMO", {"vocab": None, "words": {}}):
            got = app.rhyme_options_for("it", 6)
        self.assertTrue(got)                    # the scan still answers


class ThePromptStatesTheRule(unittest.TestCase):
    def test_the_frame_says_the_crystal_furnishes_what_was_not_said(self):
        text = crystal_prompts.turn_prompt(
            "The bin was gone at dawn.", "A style world", [{"text": "a passage"}],
            0.88, "banter")
        self.assertIn("THE STYLE WORLD DOES NOT REPLACE THE CONVERSATION'S WORDS", text)
        self.assertIn("spend the style world's vocabulary on the landings", text)
        self.assertIn("THE LANDING IS WHERE THIS STATION IS HEARD", text)
        self.assertIn("OFF THE WALL, INSIDE THE FACTS", text)
        self.assertIn("a denial the source did not make", text)

    def test_the_landings_ride_after_the_cacheable_prefix(self):
        landings = {"pairs": [{"aim": ["dawn", "gone"], "rhyme": "perfect",
                               "syllables_matched": 1, "from": "source"}],
                    "partners": {}, "use": "Decide the landing words first."}
        text = crystal_prompts.turn_prompt(
            "The bin was gone at dawn.", "A style world", [{"text": "a passage"}],
            0.88, "banter", landings=landings)
        header = "CRYSTAL LANDINGS — proven rhymes"
        self.assertIn(header, text)
        self.assertIn("dawn", text)
        prefix = crystal_prompts.frame_prefix(text)
        # the per-line block is outside the cacheable prefix...
        self.assertNotIn(header, prefix)
        self.assertNotIn("dawn", prefix)
        # ...and the static rules are inside it, so they cost nothing per ask
        self.assertIn("THE STYLE WORLD DOES NOT REPLACE", prefix)
        self.assertIn("THE LANDING IS WHERE THIS STATION IS HEARD", prefix)

    def test_the_fluid_block_no_longer_forbids_an_unusual_style_word(self):
        source = app.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("an unusual style word just to increase lexical difference", text)
        self.assertIn("SHOULD reach for the style world's own vocabulary at its landings", text)


class TheDeepRepertoire(unittest.TestCase):
    def test_the_gold_bank_is_deep_and_its_rests_meet_the_ten_second_rule(self):
        self.assertGreaterEqual(app.GOLD_MAX, 2000)
        self.assertLessEqual(app.SFX_GAP_REST, 6.0)
        self.assertLessEqual(app.TALK_INCESSANT_QUIET_MOST, 8.0)
        self.assertLessEqual(app.GAP_STOCK_FIRST_AFTER, 12.0)

    def test_the_gap_chain_spends_the_deep_bank_before_the_shallow_one(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        at = body.find("if talk_is_incessant():\n        # At the top stop the watchdog")
        self.assertGreater(at, 0)
        window = body[at:at + 2400]
        gold = window.find("sfx_fill_gap")
        cont = window.find("continuity_air")
        self.assertGreater(gold, 0)
        self.assertGreater(cont, gold, "the 400-bar bank must be tried before the 28-line one")

    def test_a_gold_bar_may_fill_a_gap_under_the_floor(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("went = await gold_fill_gap(why, floorless=floor_held)", body)
        self.assertIn("_door = _dj_speak_floorless if floorless else dj_speak", body)


class TheCallsComplete(unittest.TestCase):
    def test_a_phone_call_is_never_paged(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("A PHONE CALL IS NEVER PAGED", body)
        at = body.find("A PHONE CALL IS NEVER PAGED")
        self.assertIn("elif caller_name:", body[at:at + 1600])

    def test_a_part_aired_round_is_not_abandoned(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("if not played_any and not _system2_repeat_rows(rows, ready_meta):", body)
        self.assertIn("THESE ARE START-OF-ROUND", body)

    def test_the_station_going_off_mid_round_is_not_a_completion(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        at = body.find("a completion the station\n                        # forged for itself")
        self.assertGreater(at, 0)
        self.assertIn("missed.extend(range(_lo, len(playlist)))", body[at:at + 400])

    def test_a_cut_closing_turn_fails_a_call(self):
        with open(app.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn('and (kind != "caller" or not _cut_closing)', body)
        self.assertIn("THE CLOSING PAIR", body)


if __name__ == "__main__":
    unittest.main()
