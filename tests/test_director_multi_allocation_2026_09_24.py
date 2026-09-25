from __future__ import annotations

import unittest
from unittest import mock

import app


def _candidate(identity: str, seconds: float, prefix: str) -> dict:
    script = "\n".join(
        ("A" if index % 2 == 0 else "B") + ": " + prefix + " line " + str(index + 1)
        for index in range(5)
    )
    return {
        "id": identity,
        "seconds": seconds,
        "script": script,
        "source": {"prep_name": prefix},
    }


class DirectorMultiAllocation(unittest.TestCase):
    def test_complete_slot_exposes_every_allocated_performance(self) -> None:
        slot = {
            "id": "hour-1:banter",
            "kind": "banter",
            "prompt": "",
            "allocations": [
                {"candidate": _candidate("first", 52.0, "First"),
                 "planned_start": 100.0, "state": "ready"},
                {"candidate": _candidate("second", 53.0, "Second"),
                 "planned_start": 152.0, "state": "ready"},
            ],
        }
        with (mock.patch.object(app, "alt_find", return_value=("", None)),
              mock.patch.object(app, "_director_seat",
                                side_effect=lambda marker: marker),
              mock.patch.object(app, "dialogue_topic_review",
                                return_value={"checked": False, "ok": True,
                                              "topic": ""}),
              mock.patch.object(app, "tint_must_flow", return_value=False)):
            script = app._director_script(slot)

        self.assertEqual(script["state"], "bound")
        self.assertEqual(script["candidate"], "first")
        self.assertEqual(script["candidates"], ["first", "second"])
        self.assertEqual(script["seconds"], 105.0)
        self.assertEqual(len(script["performances"]), 2)
        self.assertEqual(len(script["turns"]), 10)
        self.assertEqual(script["turns"][4]["candidate_index"], 4)
        self.assertEqual(script["turns"][5]["candidate"], "second")
        self.assertEqual(script["turns"][5]["candidate_index"], 0)
        self.assertEqual(script["turns"][5]["performance_index"], 1)
        self.assertEqual(script["performances"][1]["turn_start"], 5)
        self.assertEqual(script["performances"][1]["turn_end"], 10)
        self.assertTrue(all(cue["candidate"] in {"first", "second"}
                            for cue in script["sfx_plan"]))
        first_cues = [cue for cue in script["sfx_plan"]
                      if cue["candidate"] == "first"]
        second_cues = [cue for cue in script["sfx_plan"]
                       if cue["candidate"] == "second"]
        self.assertLess(max(cue["after"] for cue in first_cues),
                        min(cue["after"] for cue in second_cues))

        coverage = app.director_orchestration(
            "banter", "Banter", 120.0, script,
            state="planned", review={"approved": True})
        self.assertEqual(coverage["status"], "ready")
        self.assertEqual(coverage["have"]["seconds"], 105.0)
        self.assertEqual(coverage["have"]["lines"], 10)
        self.assertEqual(coverage["short"]["seconds"], 0.0)

    def test_each_allocation_reads_its_live_shelf_script(self) -> None:
        first = _candidate("first", 20.0, "Snapshot")
        second = _candidate("second", 21.0, "Other")
        rows = {
            "first": {"script": "A: Live first.\nB: Live reply."},
            "second": {"script": "A: Live second.\nB: Another reply."},
        }

        def find(identity: str):
            return "banter", rows[identity]

        with (mock.patch.object(app, "alt_find", side_effect=find),
              mock.patch.object(app, "dialogue_entry", side_effect=lambda row: row),
              mock.patch.object(app, "dialogue_topic_review",
                                return_value={"checked": False, "ok": True,
                                              "topic": ""}),
              mock.patch.object(app, "tint_must_flow", return_value=False)):
            script = app._director_script({
                "id": "hour-1:banter", "kind": "banter",
                "allocations": [{"candidate": first}, {"candidate": second}],
            })

        self.assertTrue(script["live"])
        self.assertEqual([turn["text"] for turn in script["turns"]],
                         ["Live first.", "Live reply.",
                          "Live second.", "Another reply."])
        self.assertEqual([turn["candidate_index"] for turn in script["turns"]],
                         [0, 1, 0, 1])


if __name__ == "__main__":
    unittest.main()
