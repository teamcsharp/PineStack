import unittest
import system3


class ShortSegments(unittest.TestCase):
    def test_slot_and_free_length_rolls_stay_bounded_and_recorded(self):
        config=system3.default_config()
        for budget in (True,False):
            for seed in range(30):
                with self.subTest(budget=budget,seed=seed):
                    inputs={"road":"banter","seats":["A","B"],"turns":22,
                            "target_seconds":240,"turn_seconds":12,"budget_roll":budget,
                            "lines_rolled":not budget,"lines_min":10,"lines_max":22,"lines_base":22,
                            "short_segment_cap":6,"subject":{"topic":"a linked conversation"},"availability":{}}
                    conv=system3.plan_scene(inputs,config,system3.normalise_settings({"mode":"active","test_seed":str(seed)}),conversation_id="short-"+str(seed))
                    self.assertGreaterEqual(len(conv["turns"]),4)
                    self.assertLessEqual(len(conv["turns"]),6)
                    self.assertGreaterEqual(conv["length_roll"]["lo"],4)
                    self.assertLessEqual(conv["length_roll"]["hi"],6)
                    self.assertTrue(conv["length_roll"]["event_id"])
                    self.assertTrue(all(t.get("turn_id") for t in conv["turns"]))
                    self.assertEqual(conv["inputs"]["short_segment_cap"],6)
