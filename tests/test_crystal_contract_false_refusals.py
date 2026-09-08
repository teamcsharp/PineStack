"""#1076/#1082: the contract refusals that were the evaluator's, not the model's.

Every pair below is an exact source/candidate off six hours of the review
journal. Real changes of meaning stay refused; the cases the contract got
wrong - a filler negation, "don't know" -> "unknown", a transcript question
without its question mark, a bare "one" for "a single", "the only thing" as
emphasis, a capitalized "Yeah" required as a name, a name glued to an em
dash, a speaker label - now pass. The contract version is unchanged: the
comparison only accepts more, and every operator rule pinned in
tests/test_crystal_contract.py still holds.
"""
import unittest

from crystal_contract import VERSION, compare_contract, extract_contract


class Negation(unittest.TestCase):
    def test_negative_prefix_keeps_a_dropped_negation(self):
        report = compare_contract(
            "I don't know the specifics right now, but I feel like this whole situation is "
            "about more than just some misplaced items; it feels like a bigger game is being "
            "played in my neighborhood.",
            "Specifics unknown right now, but I feel a scheme; More than misplaced items; "
            "a bigger game in my neighborhood's theme")
        self.assertTrue(report["negation"], report["negation_basis"])

    def test_filler_negation_is_not_a_polarity_change(self):
        report = compare_contract(
            "I am trying to get some of my property back because someone has taken my "
            "belongings from my storage unit and I need them returned immediately.",
            "Trying to reclaim property from a storage unit space; Need belongings returned "
            "immediately, no time to waste")
        self.assertTrue(report["negation"], report["negation_basis"])
        self.assertEqual(report["negation_basis"], "filler negation")

    def test_negation_added_to_a_source_fact_stays_refused(self):
        report = compare_contract(
            "Just get to the point, man. We got records to spin.",
            "Just get to the point, man, no need to spin; We got records to drop, let the "
            "rhythm begin")
        self.assertFalse(report["negation"])
        # A negated claim the source never made is not a filler.
        self.assertFalse(compare_contract("Dale woulda taken that turn flat out.",
                                          "Dale woulda taken that turn flat out; No brakes on that route.",
                                          anchor_floor=0)["ok"])

    def test_dropped_negation_stays_refused(self):
        report = compare_contract(
            "Just Joe called at 3:14 AM about stolen garbage. He was caller number seven when "
            "the prize required number nine, so he did not win, taking the near-miss with "
            "strange grace before the line dropped.",
            "Joe called at three fourteen AM 'bout stolen garbage; Caller seven for prize "
            "nine, taking strange grace")
        self.assertFalse(report["negation"])
        self.assertEqual(report["negation_basis"], "negation dropped")


class Questions(unittest.TestCase):
    def test_transcript_question_may_be_punctuated(self):
        report = compare_contract(
            "saying listen to what I'm saying was there more junk food than real food no yes",
            "Hear what I'm saying, listen to the flow; More junk than real food? Yes, that's "
            "how it go")
        self.assertTrue(report["question"], report["question_basis"])
        self.assertEqual(report["question_basis"], "transcript question punctuated")
        self.assertTrue(compare_contract("Can't you feel it.", "Can't you feel it?")["question"])

    def test_dropped_question_stays_refused(self):
        report = compare_contract(
            "But how can you separate the systems? When they are constantly scanning the "
            "local area network for everything?",
            "How separate systems when they scan everything on the net; Local area network "
            "scanning, a digital threat")
        self.assertFalse(report["question"])

    def test_invented_question_on_a_punctuated_statement_stays_refused(self):
        report = compare_contract(
            "Exactly. It feels like a tangible piece of control being snatched away, and I "
            "just need that simple act of getting it back to feel like a real victory.",
            "Exactly; tangible piece of control snatched away; Need that simple act of "
            "getting it back to feel like a victory, okay?")
        self.assertFalse(report["question"])
        self.assertFalse(compare_contract("You keep the copper plate.",
                                          "Can you keep the copper plate?")["question"])
        self.assertFalse(compare_contract("You keep the copper plate",
                                          "Can you keep the copper plate?")["question"])


class Quantities(unittest.TestCase):
    def test_bare_one_for_a_single_is_the_same_count(self):
        report = compare_contract(
            "That buzzing feels like trying to process a whole world in a single breath",
            "Buzzing like a whole world processed in one breath")
        self.assertTrue(report["entities"], report)
        report = compare_contract("Reclaiming my space is what matters to me.",
                                  "Reclaiming my space is the only thing that can rescue me")
        self.assertTrue(report["entities"], report)
        deep = compare_contract("It was a deep one.", "It ran deep.")
        self.assertEqual(deep["missing_numbers"], [], deep)
        self.assertTrue(deep["ambiguous_numbers"]["source"])

    def test_counted_one_still_binds(self):
        self.assertFalse(compare_contract("He was caller number seven.", "He was caller number one.")["entities"])
        self.assertFalse(compare_contract("Mara needs one copper plate.", "Mara needs only copper plates.")["entities"])
        self.assertFalse(compare_contract("Mara needs a copper plate.", "Mara needs one copper plate and one frame.")["entities"])
        self.assertEqual(extract_contract("one hundred people")["numbers"][0]["value"], "100")
        # A source "one thing" keeps its uniqueness; a rewrite may say "the only thing".
        self.assertTrue(compare_contract("The one thing I keep is the plate.",
                                         "The only thing I keep is the plate.")["entities"])
        self.assertFalse(compare_contract("The one thing I keep is the plate.",
                                          "The thing I keep is the plate.")["entities"])


class Names(unittest.TestCase):
    def test_capitalized_opener_is_not_a_name_when_it_is_how_speech_starts(self):
        report = compare_contract(
            "Yeah, I'm not sure what you're saying but the fact is if I went out there and "
            "built myself a cabin you would have been happy.",
            "Not sure what you're saying, but here is a fact; If I built a cabin, your "
            "outlook would be intact")
        self.assertEqual(report["missing_names"], [])
        self.assertNotIn("yeah", [row["normalized"] for row in report["name_candidates"]])
        for text in ("Grab a plate and go.", "Cuz the record is spinning.", "Just get to the point."):
            with self.subTest(text=text):
                self.assertEqual(extract_contract(text)["names"], [])

    def test_real_names_and_unknown_openers_still_bind(self):
        report = compare_contract("Sarah Sherman called at 3:04 AM.", "She called at 3:04 AM.")
        self.assertEqual([row["text"] for row in report["missing_names"]], ["Sarah", "Sherman"])
        self.assertFalse(compare_contract("Mara holds the copper plate.", "Nora holds the copper plate.")["entities"])
        self.assertFalse(compare_contract("Dale woulda taken that turn.", "He woulda taken that turn.")["entities"])
        self.assertFalse(compare_contract("Ious. The king holds the plate.", "The king holds the plate.")["entities"])

    def test_em_dash_does_not_glue_a_name(self):
        report = compare_contract(
            "Freshing. The perfect microcosm of the animal world.",
            "Freshing—animal world microcosm, a perfect sphere")
        self.assertEqual(report["missing_names"], [])

    def test_speaker_label_is_not_dialogue(self):
        report = compare_contract(
            'Maxine Brown: "Topic stopped being abstract when magnets slid down the door"',
            "Topic stopped being abstract when magnets slid down the door; one by one")
        self.assertEqual(report["missing_names"], [])
        self.assertEqual([row["text"] for row in report["possible_names_missing"]], ["Maxine", "Brown"])
        # The same name inside the quote is still a name.
        spoken = compare_contract('Maxine Brown: "Tell Maxine the magnets slid."', "Tell her the magnets slid.")
        self.assertEqual([row["text"] for row in spoken["missing_names"]], ["Maxine"])


class Version(unittest.TestCase):
    def test_the_contract_version_is_unchanged(self):
        self.assertEqual(VERSION, 3)
        self.assertEqual(compare_contract("Mara keeps the plate.", "Mara keeps the plate, mate.")["contract_version"], 3)


if __name__ == "__main__":
    unittest.main()
