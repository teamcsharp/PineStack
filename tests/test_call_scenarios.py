from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from call_scenarios import (BEATS, BUILTIN_SCENARIOS, CATALOG_VERSION,
                            MAX_CATALOG_BYTES, call_aired_conclusion_report,
                            call_conclusion_report,
                            call_path_draw, call_scenario_clause,
                            load_scenario_catalog, save_scenario_catalog,
                            select_call_scenario)


def scenario() -> dict:
    return {
        "id": "greenhouse-roof", "premise": "the missing greenhouse roof",
        "want": "have the detail taken seriously", "stance": "worried but precise",
        "register": "ordinary caller", "boundary": "do not blame June without evidence",
        "heat": 0.6, "system_prompt": "Keep the caller's account grounded.",
        "conclusion_pool": [
            {"id": "heard", "text": "Feel that the hosts heard the point",
             "proof_phrases": ["you heard me", "I feel heard"],
             "weight": 3},
            {"id": "clearer", "text": "Leave with a clearer understanding",
             "proof_phrases": ["I see it now"], "weight": 1},
        ],
    }


def catalog(*rows: dict) -> dict:
    return {"schema_version": CATALOG_VERSION, "scenarios": list(rows),
            "notes": "Keep the case outcome authoritative."}


class FixedRandom:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)


class CallScenarioTests(unittest.TestCase):
    def test_draws_six_ordered_beats_and_one_conclusion(self) -> None:
        plan = call_path_draw(
            scenario(), caller_name="Doreen",
            topic="Act 3: the missing greenhouse roof",
            rng=random.Random(17))
        self.assertEqual([beat["beat"] for beat in plan["beats"]], list(BEATS))
        self.assertEqual(plan["subject"], "the missing greenhouse roof")
        self.assertEqual(plan["caller_name"], "Doreen")
        self.assertIn(plan["conclusion"]["id"], {"heard", "clearer"})
        self.assertEqual(json.loads(json.dumps(plan)), plan)

    def test_seed_replays_the_whole_draw(self) -> None:
        first = call_path_draw(scenario(), rng=random.Random(981))
        again = call_path_draw(scenario(), rng=random.Random(981))
        self.assertEqual(first, again)
        paths = {tuple(beat["id"] for beat in call_path_draw(
            scenario(), rng=random.Random(seed))["beats"]) for seed in range(120)}
        self.assertGreater(len(paths), 80)

    def test_one_direction_colors_existing_protocol_without_extra_turns(self) -> None:
        plan = call_path_draw(
            scenario(), case_outcome="The hosts promise to chase the repair",
            rng=random.Random(8))
        clause = call_scenario_clause(plan)
        self.assertEqual(clause.count("SCENARIO DIRECTION"), 1)
        self.assertIn(plan["subject"], clause)
        for key in ("premise", "want", "stance", "register", "boundary"):
            self.assertIn(plan[key], clause)
        self.assertIn(plan["conclusion"]["text"], clause)
        self.assertIn(plan["case_outcome"], clause)
        self.assertIn("not a new event or procedural ending", clause)
        self.assertIn("second to last", clause)
        for beat in plan["beats"]:
            self.assertEqual(clause.count(beat["cue"]), 1)
        self.assertNotIn("\n", clause)

    def test_partial_override_and_weights(self) -> None:
        custom = scenario()
        custom["path_map"] = {"motive": [
            {"id": "quiet", "cue": "ask quietly", "weight": 1},
            {"id": "urgent", "cue": "ask urgently", "weight": 9},
        ]}
        low = call_path_draw(custom, rng=FixedRandom(*([0.01] * 7)))
        high = call_path_draw(custom, rng=FixedRandom(*([0.99] * 7)))
        self.assertEqual(low["beats"][0]["id"], "quiet")
        self.assertEqual(high["beats"][0]["id"], "urgent")
        self.assertEqual(len(low["beats"]), 6)
        self.assertEqual(low["conclusion"]["id"], "heard")
        self.assertEqual(high["conclusion"]["id"], "clearer")

    def test_bad_scenario_data_is_rejected_before_drawing(self) -> None:
        for change in (
            {"want": ""}, {"heat": float("nan")},
            {"conclusion_pool": []},
            {"path_map": {"unknown": []}},
            {"path_map": []},
            {"path_map": {"motive": [{"id": "x", "cue": "a", "weight": 0}]}},
            {"path_map": {"motive": [
                {"id": "x", "cue": "a"}, {"id": "x", "cue": "b"}]}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                call_path_draw({**scenario(), **change}, rng=random.Random(1))

    def test_conclusion_requires_explicit_nontrivial_proof(self) -> None:
        for proof in ([], ["repair"], [""], ["  "]):
            custom = scenario()
            custom["conclusion_pool"] = [
                {"id": "heard", "text": "Feel heard", "proof_phrases": proof}]
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                call_path_draw(custom, rng=random.Random(1))

    def test_report_checks_only_the_last_three_turns_and_is_soft(self) -> None:
        plan = call_path_draw(scenario(), rng=FixedRandom(*([0.01] * 7)))
        turns = [
            ("C", "You heard me today."),
            ("A", "What happened to the roof?"),
            ("C", "The glass fell at dawn."),
            ("A", "Thank you for calling."),
        ]
        missing = call_conclusion_report(plan, turns)
        self.assertFalse(missing["matched"])
        self.assertFalse(missing["aired_verified"])
        self.assertEqual(len(missing["soft_faults"]), 1)
        turns[-2] = ("C", "I FEEL, heard now.")
        stated = call_conclusion_report(plan, turns)
        self.assertTrue(stated["matched"])
        self.assertEqual(stated["matched_phrase"], "I feel heard")
        self.assertFalse(stated["aired_verified"])
        with self.assertRaisesRegex(ValueError, "receipt"):
            call_conclusion_report(plan, turns, source="aired")

    def test_report_rejects_unparsed_transcript_and_unknown_source(self) -> None:
        plan = call_path_draw(scenario(), rng=random.Random(1))
        with self.assertRaises(ValueError):
            call_conclusion_report(plan, "C: I feel heard.")
        with self.assertRaises(ValueError):
            call_conclusion_report(plan, [], source="estimated")

    def test_proof_phrase_cannot_cross_a_turn_boundary(self) -> None:
        plan = call_path_draw(scenario(), rng=FixedRandom(*([0.01] * 7)))
        report = call_conclusion_report(plan, [
            ("A", "I feel"), ("C", "heard about it"),
            ("A", "Thank you for calling")])
        self.assertFalse(report["matched"])

    def test_air_report_uses_only_heard_primary_caller_resolution(self) -> None:
        plan, lines, rows = self.air_fixture()
        result = call_aired_conclusion_report(
            plan, list(reversed(rows)), sid="call-one", expected_lines=lines)
        self.assertEqual(result["status"], "matched")
        self.assertTrue(result["aired_verified"])
        self.assertEqual(result["matched_phrase"], "I feel heard")
        self.assertEqual(result["source"], "air_log_page_ack")
        self.assertEqual(result["expected_line_ids"], ["l1", "l2", "l3", "l4"])

    @staticmethod
    def air_fixture() -> tuple[dict, list[dict], list[dict]]:
        plan = call_path_draw(scenario(), caller_name="Doreen",
                              rng=FixedRandom(*([0.01] * 7)))
        lines = [
            {"line_id": "l0", "kind": "dialogue", "who": "caller", "turn": 0,
             "text": "I feel heard (draft only)"},
            {"line_id": "l1", "kind": "dialogue", "who": "dj", "turn": 1},
            {"line_id": "l2", "kind": "dialogue", "who": "caller", "turn": 2},
            {"line_id": "l3", "kind": "dialogue", "who": "caller", "turn": 2},
            {"line_id": "l4", "kind": "dialogue", "who": "dj", "turn": 3},
            {"line_id": "sfx", "kind": "sfx", "who": "board", "turn": -1},
        ]
        words = ["Please explain.", "I feel", "heard now.", "Thanks for calling."]
        rows = [
            {"id": line["line_id"], "sid": "call-one", "turn": line["turn"],
             "who": line["who"], "name": "Doreen" if line["who"] == "caller" else "DJ",
             "caller": "Doreen" if line["who"] == "caller" else "",
             "round": "caller", "kind": "call", "text": words[index],
             "aired": "stream", "heard_ack_at": 100.0 + index,
             "heard_ack_by": "page", "source": "caller_topic.json"}
            for index, line in enumerate(lines[1:5])
        ]
        return plan, lines, rows

    def test_air_report_distinguishes_no_playback_and_partial_playback(self) -> None:
        plan, lines, rows = self.air_fixture()
        published = [{**row, "heard_ack_at": None, "heard_ack_by": ""}
                     for row in rows]
        for candidate in ([], published,
                          [{**row, "heard_ack_by": "set"} for row in rows]):
            with self.subTest(candidate=candidate):
                report = call_aired_conclusion_report(
                    plan, candidate, sid="call-one", expected_lines=lines)
                self.assertEqual(report["status"], "not_aired")
                self.assertFalse(report["aired_verified"])
        partial = call_aired_conclusion_report(
            plan, rows[:-1], sid="call-one", expected_lines=lines)
        self.assertEqual(partial["status"], "insufficient_evidence")
        self.assertFalse(partial["aired_verified"])

    def test_air_report_requires_exact_call_identity_and_receipt_order(self) -> None:
        plan, lines, rows = self.air_fixture()
        variants = (
            [{**row, "sid": "another-call"} for row in rows],
            [*rows[:-1], {**rows[-1], "heard_ack_at": 99.0}],
            [*rows[:-1], {**rows[-1], "turn": 9}],
            [*rows[:1], {**rows[1], "name": "Another caller"}, *rows[2:]],
            [*rows[:1], {**rows[1], "caller": "Another caller"}, *rows[2:]],
            [*rows[:1], {**rows[1], "who": "dj"}, *rows[2:]],
            [*rows, {**rows[2], "text": "different"}],
        )
        for index, candidate in enumerate(variants):
            with self.subTest(index=index):
                report = call_aired_conclusion_report(
                    plan, candidate, sid="call-one", expected_lines=lines)
                self.assertFalse(report["aired_verified"])
                self.assertIn(report["status"], {"not_aired", "insufficient_evidence"})

    def test_air_report_does_not_use_draft_or_host_phrase_as_proof(self) -> None:
        plan, lines, rows = self.air_fixture()
        earlier = {**rows[1], "id": "l0", "turn": 0,
                   "text": "I feel heard.", "heard_ack_at": 98.0}
        rows[1]["text"] = "I can understand."
        rows[2]["text"] = "Thank you."
        rows[3]["text"] = "I feel heard by you."
        report = call_aired_conclusion_report(
            plan, [earlier, *rows], sid="call-one", expected_lines=lines)
        self.assertEqual(report["status"], "missed")
        self.assertFalse(report["aired_verified"])
        rows[1]["text"] = "I feel heard."
        rows[2]["text"] = "Thank you."
        rows[3]["text"] = "Goodbye."
        self.assertEqual(call_aired_conclusion_report(
            plan, rows, sid="call-one", expected_lines=lines)["status"], "matched")
        rows[1]["text"] = "x" * 600
        rows[2]["text"] = "Thank you."
        self.assertEqual(call_aired_conclusion_report(
            plan, rows, sid="call-one", expected_lines=lines)["status"],
            "insufficient_evidence")

    def test_air_report_requires_terminal_caller_and_host_metadata(self) -> None:
        plan, lines, rows = self.air_fixture()
        with self.assertRaisesRegex(ValueError, "sign-off"):
            call_aired_conclusion_report(plan, rows, sid="call-one",
                                         expected_lines=lines[:-2])
        with self.assertRaisesRegex(ValueError, "sid"):
            call_aired_conclusion_report(plan, rows, sid="", expected_lines=lines)

    def test_missing_corrupt_and_oversize_files_fall_back_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caller_scenarios.json"
            missing = load_scenario_catalog(path)
            self.assertEqual(missing["source"], "builtin")
            self.assertEqual(missing["fallback_reason"], "missing")
            self.assertEqual(len(missing["scenarios"]), len(BUILTIN_SCENARIOS))
            self.assertFalse(path.exists())

            for data, reason in ((b"{bad", "invalid"),
                                 (b"x" * (MAX_CATALOG_BYTES + 1), "oversize")):
                path.write_bytes(data)
                fallback = load_scenario_catalog(path)
                self.assertEqual(fallback["source"], "builtin")
                self.assertEqual(fallback["fallback_reason"], reason)
                self.assertEqual(path.read_bytes(), data)

    def test_builtins_are_diverse_and_only_add_dramatic_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pool = load_scenario_catalog(Path(directory) / "missing.json")
        rows = pool["scenarios"]
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        self.assertGreaterEqual(len(rows), 5)
        self.assertLess(min(row["heat"] for row in rows), 0.2)
        self.assertGreater(max(row["heat"] for row in rows), 0.8)
        self.assertTrue(all("outcome" not in row for row in rows))
        for row in rows:
            plan = call_path_draw(row, topic="the station's missing record",
                                  case_outcome="The hosts promise to search for it",
                                  rng=random.Random(4))
            self.assertEqual(len(plan["beats"]), 6)
            clause = call_scenario_clause(plan)
            self.assertIn("The hosts promise to search for it", clause)
            self.assertIn("not a new event or procedural ending", clause)

    def test_catalog_round_trip_preserves_notes_and_editable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caller_scenarios.json"
            edited = scenario()
            edited["notes"] = "A private editorial reminder."
            edited["path_map"] = {"motive": [
                {"id": "ask", "cue": "ask for an answer", "weight": 2}]}
            saved = save_scenario_catalog(path, catalog(edited))
            loaded = load_scenario_catalog(path)
            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["source"], "file")
            self.assertEqual(loaded["notes"], "Keep the case outcome authoritative.")
            self.assertEqual(loaded["scenarios"][0]["notes"], edited["notes"])
            self.assertEqual(loaded["scenarios"][0]["path_map"]["motive"][0]["id"], "ask")
            self.assertEqual(len(list(Path(directory).glob("*.tmp"))), 0)

    def test_weighted_scenario_draw_respects_enable_and_case_heat(self) -> None:
        cool = {**scenario(), "id": "cool", "heat": 0.1, "weight": 1}
        hot = {**scenario(), "id": "hot", "heat": 0.9, "weight": 9}
        pool = catalog(cool, hot)
        self.assertEqual(select_call_scenario(pool, rng=FixedRandom(0.01))["id"], "cool")
        self.assertEqual(select_call_scenario(pool, rng=FixedRandom(0.99))["id"], "hot")
        self.assertEqual(select_call_scenario(
            pool, target_heat=0.0, rng=FixedRandom(0.99))["id"], "cool")
        self.assertIsNone(select_call_scenario(pool, target_heat=0.5))
        self.assertIsNone(select_call_scenario(catalog(
            {**cool, "enabled": False}, {**hot, "enabled": False})))

    def test_invalid_catalog_or_failed_replace_keeps_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caller_scenarios.json"
            save_scenario_catalog(path, catalog(scenario()))
            original = path.read_bytes()
            bad = catalog({**scenario(), "weight": float("nan")})
            with self.assertRaises(ValueError):
                save_scenario_catalog(path, bad)
            self.assertEqual(path.read_bytes(), original)
            with mock.patch("call_scenarios.os.replace", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    save_scenario_catalog(path, catalog(scenario()))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_catalog_rejects_duplicate_ids_wrong_version_and_bad_fields(self) -> None:
        row = scenario()
        for bad in (
            catalog(row, row),
            {**catalog(row), "schema_version": 2},
            catalog({**row, "enabled": "yes"}),
            catalog({**row, "weight": 1e308}),
            catalog({**row, "notes": "n" * 501}),
            catalog({**row, "surprise": "silently lost"}),
            catalog(*[{**row, "id": f"row-{i}"} for i in range(33)]),
        ):
            with self.subTest(bad=repr(bad)[:60]), self.assertRaises(ValueError):
                select_call_scenario(bad)

    def test_valid_json_with_bad_schema_falls_back_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caller_scenarios.json"
            data = b'{"schema_version":2,"scenarios":[]}'
            path.write_bytes(data)
            loaded = load_scenario_catalog(path)
            self.assertEqual(loaded["fallback_reason"], "invalid")
            self.assertEqual(path.read_bytes(), data)

    def test_save_rejects_catalog_above_byte_limit_before_creating_file(self) -> None:
        long_paths = {beat: [
            {"id": f"path-{index}", "cue": "c" * 140}
            for index in range(16)] for beat in BEATS}
        rows = [{**scenario(), "id": f"row-{index}", "path_map": long_paths}
                for index in range(32)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caller_scenarios.json"
            with self.assertRaisesRegex(ValueError, "size limit"):
                save_scenario_catalog(path, catalog(*rows))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
