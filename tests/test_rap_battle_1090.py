"""#1090: "I want the entire station being handled and rationalized in system 2
as a rap battle for the station... a constantly streaming rap battle between the
hosts, callers, manager, sfx guy, and whoever else is added to the mix."

The station had every ingredient and no thread: each round was written as if the
room had just met. These are the rules that make the day one argument.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from rap_battle import COMBATANTS, RapBattle


class BattleThreadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.now = [1000.0]
        self.battle = RapBattle(Path(self.dir.name) / "battle.json",
                                clock=lambda: self.now[0])

    def test_only_a_combatant_speaking_real_words_is_a_bar(self):
        self.assertEqual(self.battle.note("board", "a door slams"), 0)
        self.assertEqual(self.battle.note("dj", "yeah"), 0)     # too short to answer
        self.assertEqual(self.battle.note("nobody", "a full sentence of words"), 0)
        self.assertEqual(self.battle.note("drop", "the SFX guy throws one too"), 1)
        self.assertEqual(self.battle.note("manager", "upstairs has something to add"), 2)

    def test_the_clause_quotes_the_last_bar_and_forbids_its_landing(self):
        self.battle.note("caller", "your ledger reads like a hagiography")
        text = self.battle.clause()
        self.assertIn("ANSWER THIS", text)
        self.assertIn("the caller", text)
        self.assertIn("your ledger reads like a hagiography", text)
        self.assertIn('Do not land on "hagiography"', text)
        self.assertIn("answering a word with itself is a forfeit", text)

    def test_a_landing_is_taken_from_the_last_bar_of_a_rapped_turn(self):
        self.battle.note("dj", "plates came in late / the ledger says you signed at eight")
        self.assertIn('Do not land on "eight"', self.battle.clause())

    def test_an_opening_volley_has_nothing_to_answer(self):
        text = self.battle.clause()
        self.assertIn("You open the volley", text)
        self.assertNotIn("ANSWER THIS", text)

    def test_a_stale_bar_is_not_answered_but_the_battle_continues(self):
        self.battle.note("dj", "a bar thrown a long time ago")
        self.now[0] += 4000.0                       # past the answer window
        text = self.battle.clause()
        self.assertIn("You open the volley", text)
        self.assertIn("Round 2", text)              # the night did not restart

    def test_the_same_seat_twice_is_pressing_not_repeating(self):
        self.battle.note("dj", "the first half of the argument here")
        self.assertIn("pressing your own point further", self.battle.clause("dj"))
        self.assertNotIn("pressing your own point further", self.battle.clause("cohost"))

    def test_the_standing_counts_bars_and_answers_without_announcing_them(self):
        self.battle.note("dj", "the opening bar of the night")
        self.battle.note("caller", "the answer to that opening bar")
        self.battle.note("caller", "and the caller presses it again")
        state = self.battle.read()
        self.assertEqual(state["standing"]["dj"]["bars"], 1)
        self.assertEqual(state["standing"]["caller"]["bars"], 2)
        self.assertEqual(state["standing"]["caller"]["answers"], 1)
        self.assertIn("Nobody concedes and nobody announces the score",
                      self.battle.clause())

    def test_the_thread_is_bounded_and_survives_a_reload(self):
        for i in range(20):
            self.battle.note("dj" if i % 2 else "cohost", f"bar number {i} of the night")
        self.assertLessEqual(len(self.battle.read()["thread"]), 6)
        fresh = RapBattle(self.battle.path, clock=lambda: self.now[0])
        self.assertEqual(fresh.read()["round"], 20)
        self.assertIn("bar number 19", fresh.clause())

    def test_the_facts_still_govern_and_the_heat_is_aimed_at_the_argument(self):
        text = self.battle.clause()
        self.assertIn("The facts still govern absolutely", text)
        self.assertIn("battle of WORDING", text)
        self.assertIn("never invent an insult about a real person's race, sex or "
                      "religion", text)

    def test_every_seat_the_operator_named_is_a_combatant(self):
        for seat in ("dj", "cohost", "third", "caller", "manager", "drop"):
            self.assertIn(seat, COMBATANTS)


class BattleRidesEveryRoundTests(unittest.TestCase):
    def test_the_schedule_clause_carries_the_battle_into_every_slot(self):
        clause = app._schedule_clause(
            "canonical hour", {"label": "News coverage", "kind": "news"},
            "read the wires")
        self.assertIn("THIS ROUND IS THE", clause)          # still the schedule
        self.assertIn("THE BATTLE (#1090)", clause)         # ...and the battle
        self.assertIn("it is ALSO your turn in the battle", clause)

    def test_a_broken_ledger_never_costs_a_round_its_prompt(self):
        with mock.patch.object(app, "_BATTLE") as broken:
            broken.clause.side_effect = RuntimeError("ledger unreadable")
            self.assertEqual(app.rap_battle_clause(), "")
            broken.note.side_effect = RuntimeError("ledger unreadable")
            self.assertEqual(app.rap_battle_note("dj", "a bar"), 0)

    def test_an_aired_line_is_what_advances_the_thread(self):
        # The station's own definition of "went out" is the one the battle uses.
        source = Path(app.__file__).read_text(encoding="utf-8", errors="ignore")
        at = source.find("_AIRLOG_SEAT_LAST[row[\"who\"]] = max(")
        self.assertGreater(at, 0)
        self.assertIn("rap_battle_note(", source[at:at + 900])


if __name__ == "__main__":
    unittest.main()
