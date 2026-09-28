"""[s3-callend] The station's side of a call's rolled end (tools/system3_callend_patch.py).

Imports app (run in the container). Nothing here writes the station's data: `_RADIO` is
patched per test, the call log, the story desk and the pipeline log are mocked.

  - the checker keys on the planned WRAP CALL node: a call that ends the way the roulette
    said ("tells them to enjoy the ashes", no goodbye) is not thrown away for it, and the
    caller's rebuttal must still be second to last; a call System 3 did not plan is graded
    exactly as before
  - the angle's own ending (every call road's wording) and the "still trying to shift a
    painting" offer give way to the rolled end
  - the topic contract grades the call without its rolled end
  - the painting the last segment sold is read off what the station recorded as it aired
  - the gallery effect acts on the pile by the desk
  - the booth row and the call log say the rolled end as the reason
"""
import time
import unittest
from unittest import mock

import app

SCRIPT = ("A: The request line is ringing. Pine Box FM, you're live; go ahead.\n"
          "C: Salem here, calling from a dimly lit corner of the city.\n"
          "A: Salem, good to have you. What made you call?\n"
          "C: My garbage was stolen, the whole bin.\n"
          "B: The whole bin was stolen? What was in the bin?\n"
          "C: The bin was gone at dawn, and the lid too.\n"
          "A: The lid too? Did anyone see the bin go?\n"
          "C: Nobody saw the bin go, but the lid turned up in the park.\n"
          "A: Salem, the painting we had up, the harbour at dawn, is yours at 298 dollars.\n"
          "C: I'll take the painting, and I am setting the painting on fire right now.\n"
          "B: You are burning the painting on the phone?\n"
          "C: The painting is ash already and I regret nothing at all.\n"
          "A: Enjoy the ashes, Salem. Click.")
SIGN_OFF = "a host does not give the call a clear spoken sign-off"
RESOLVED = "the caller does not resolve the exchange immediately before the host signs off"
CALLEND = {"planned": True, "by": "system3", "conversation_id": "c1",
           "resolve": {"id": "buys_burns", "label": "Buys it, then decides to set it on fire",
                       "category": "painting", "effect": "burnt"},
           "wrap": {"planned": True, "id": "enjoy_the_ashes", "label": "Tells them to enjoy the ashes",
                    "polite": False, "seat": "A", "who": "Dill", "dead_line": False},
           "turns": 13, "end_turns": 5,
           "says": 'the caller\'s wheel landed on "Buys it, then decides to set it on fire"; Dill wraps the call'}


class CheckerTests(unittest.TestCase):
    def test_the_planned_wrap_is_the_sign_off_whatever_its_words(self):
        plain = app.call_flow_report(SCRIPT, caller_name="Salem", include_shelf=False)
        self.assertIn(SIGN_OFF, plain["faults"], "a call System 3 did not plan is graded as before")
        self.assertIn(RESOLVED, plain["faults"])
        self.assertEqual(plain["callend"], {})
        rolled = app.call_flow_report(SCRIPT, caller_name="Salem", include_shelf=False, callend=CALLEND)
        self.assertNotIn(SIGN_OFF, rolled["faults"])
        self.assertNotIn(RESOLVED, rolled["faults"])
        self.assertTrue(rolled["closed"] and rolled["resolved"])
        self.assertEqual(rolled["callend"]["sign_off"], "the planned WRAP CALL node")
        self.assertTrue(rolled["callend"]["seat_as_planned"])
        # every other leg is exactly what it was
        self.assertEqual(sorted(set(plain["faults"]) - {SIGN_OFF, RESOLVED}), sorted(rolled["faults"]))

    def test_the_rebuttal_must_still_be_second_to_last_and_the_wrap_a_station_seat(self):
        late = SCRIPT + "\nB: And that is the end of that."
        got = app.call_flow_report(late, caller_name="Salem", include_shelf=False, callend=CALLEND)
        self.assertIn(RESOLVED, got["faults"])
        caller_last = SCRIPT.rsplit("\n", 1)[0]
        got = app.call_flow_report(caller_last, caller_name="Salem", include_shelf=False, callend=CALLEND)
        self.assertIn(SIGN_OFF, got["faults"])

    def test_a_polite_wrap_still_passes_by_its_words(self):
        polite = SCRIPT.rsplit("\n", 1)[0] + "\nA: Thanks for calling, Salem. Take care."
        got = app.call_flow_report(polite, caller_name="Salem", include_shelf=False, callend=CALLEND)
        self.assertNotIn(SIGN_OFF, got["faults"])
        self.assertEqual(got["callend"]["sign_off"], "spoken")


class AngleTests(unittest.TestCase):
    def test_every_roads_ending_gives_way(self):
        generated = ("Take the call properly. THE PAIR ARE STILL TRYING TO SHIFT A PAINTING. At some point they ask. "
                     "One quick beat; never the whole call. By the end, the caller WINS a prize. The PENULTIMATE turn "
                     "is Salem landing it. Then back to the music. Format the caller's lines as 'C: ...'.")
        got = app.s3_callend_angle(generated, CALLEND)
        self.assertNotIn("WINS a prize", got)
        self.assertNotIn("STILL TRYING TO SHIFT", got)
        self.assertIn("Format the caller's lines", got)
        self.assertIn("HOW THIS CALL ENDS WAS ROLLED", got)
        caller_road = ("Let it RUN. The call must END this way, arrived at honestly over the last two or three turns: "
                       "the caller hangs up furious. The PENULTIMATE turn is Salem. Then cut back to the record. "
                       "By the end of the call, the caller hangs up furious. Format the caller's lines as 'C: ...'.")
        got = app.s3_callend_angle(caller_road, CALLEND)
        self.assertNotIn("hangs up furious", got)
        self.assertIn("Then cut back to the record.", got)
        general = dict(CALLEND, resolve=dict(CALLEND["resolve"], category="general"))
        self.assertIn("STILL TRYING TO SHIFT", app.s3_callend_angle(generated, general),
                      "the mid-call offer stays when the wheel is not the painting's")
        self.assertEqual(app.s3_callend_angle(generated, None), generated)

    def test_the_topic_contract_leaves_the_rolled_end_out(self):
        turns = [("A", str(i)) for i in range(13)]
        got = app.s3_callend_topic_turns(turns, {"callend": CALLEND})
        self.assertEqual(len(got), 13 - 5 + 1)
        self.assertEqual(got[-1], turns[-1], "the last turn stays: the contract sets it aside as the sign-off")
        self.assertEqual(app.s3_callend_topic_turns(turns, {}), turns)


class GalleryTests(unittest.TestCase):
    def test_the_painting_the_last_segment_sold(self):
        now = time.time()
        radio = {"hawking": {}, "ad_now": {},
                 "gallery_now": {"at": now - 300, "images": [{"name": "a_00001_.png", "desc": "a red barn"},
                                                             {"name": "harbour_00275_.png", "desc": "a boat"}]},
                 "chat": [{"ts": now - 290, "who": "dj", "text": "Look at the boat.", "images": ["harbour_00275_.png"]},
                          {"ts": now - 280, "who": "cohost", "text": "298 dollars, first caller takes it.",
                           "images": ["harbour_00275_.png"]}]}
        with mock.patch.dict(app._RADIO, radio):
            got = app.system3_painting_on_offer(1200)
            self.assertEqual(got["image"], "harbour_00275_.png")
            self.assertEqual(got["price"], 298)
            self.assertEqual(got["terms"], "first caller takes it")
            self.assertEqual(got["kind"], "gallery")
            self.assertEqual(app.system3_painting_on_offer(120), {}, "older than the window: not the last segment")
        radio["ad_now"] = {"at": now - 30, "image": "z_00302_.png", "title": "",
                           "product": 'the original painting "x" — in it: a cat — from the Pine Box gallery, '
                                      '450 dollars, first caller takes it', "price": 0}
        with mock.patch.dict(app._RADIO, radio):
            got = app.system3_painting_on_offer(1200)
            self.assertEqual((got["kind"], got["image"], got["price"], got["desc"]), ("ad", "z_00302_.png", 450, "a cat"))
        with mock.patch.dict(app._RADIO, {"hawking": {}, "ad_now": {}, "gallery_now": {}, "chat": []}):
            self.assertEqual(app.system3_painting_on_offer(1200), {})

    def test_the_outcome_acts_on_the_pile(self):
        with mock.patch.dict(app._RADIO, {"hawk_unsold": [{"name": "p.png"}, {"name": "q.png"}],
                                          "gallery_shown": []}), mock.patch.object(app, "pipeline_log"):
            got = app.system3_gallery_outcome("burnt", {"image": "p.png"}, "c1")
            self.assertEqual(got["off_the_pile"], 1)
            self.assertEqual([p["name"] for p in app._RADIO["hawk_unsold"]], ["q.png"])
            self.assertEqual(app._RADIO["gallery_shown"][-1], "p.png")
            got = app.system3_gallery_outcome("unsold", {"image": "r.png", "price": 10}, "c2")
            self.assertTrue(got["on_the_pile"])
            self.assertEqual(app._RADIO["hawk_unsold"][-1]["name"], "r.png")
            self.assertFalse(app.system3_gallery_outcome("sold", {}, "c3")["applied"])


class CallEndedTests(unittest.TestCase):
    def test_the_booth_and_the_log_say_the_rolled_end(self):
        live = {"id": "x1", "meta": {"callend": CALLEND}, "transcript": [{"who": "dj", "name": "", "text": "hi"}]}
        with mock.patch.dict(app._CALL_LIVE, live, clear=True), mock.patch.dict(app._RADIO, {"chat": []}), \
                mock.patch.object(app, "call_log_add") as logged, mock.patch.object(app, "story_note_call"), \
                mock.patch.object(app, "pipeline_log"), mock.patch.object(app, "call_line_free"):
            app.call_ended("Salem", "line 12", time.time() - 60, {"id": "r1", "text": "the caller hangs up furious"}, 12)
            row = logged.call_args.args[0]
            self.assertTrue(row["rule"].startswith("System 3: "), row["rule"])
            self.assertEqual(row["callend"]["resolve"]["id"], "buys_burns")
            self.assertTrue(app._RADIO["chat"][-1]["reason"].startswith("System 3"))


if __name__ == "__main__":
    unittest.main()
