"""Isolated final-word handoff tests: no app, station, writers or transport."""
import asyncio
import copy
import unittest
import system3
import system3_handoff as engine


PEOPLE = [
    {"seat": "A", "who": "dj", "name": "Dill"},
    {"seat": "B", "who": "cohost", "name": "Skip"},
    {"seat": "D", "who": "third", "name": "Billy"},
]


def long_text(count=12):
    return " ".join("Photograph %d catches a different light across the abandoned station windows." % n
                    for n in range(count))


def fixture(texts, seats=None, policy=None, seed="handoff-test"):
    config = system3.default_config()
    config["handoff"] = engine.validate_config(dict({"thresholds": [250], "continue_probability": 0.,
        "respond_probability": 1.}, **(policy or {})))
    seats = seats or ["A"] * len(texts)
    conv = system3.new_conversation({"seats": ["A", "B", "D"], "names": {p["seat"]: p["name"] for p in PEOPLE},
        "roles": {p["seat"]: p["who"] for p in PEOPLE}, "turns": max(2, len(texts))},
        config, system3.normalise_settings({}), seed=seed, conversation_id="test-conversation")
    for i, (seat, text) in enumerate(zip(seats, texts)):
        person = next(p for p in PEOPLE if p["seat"] == seat)
        turn = {"turn_id": "test:t%02d" % i, "index": i, "script_index": None,
            "speaker": seat, "name": person["name"], "who": person["who"], "phase": "OPEN",
            "step": "reply", "step_label": "Adds their own thought", "cycle": 0, "text": "",
            "status": "planned", "decisions": [], "directions": [], "protocol": "original protocol",
            "performance": {"original": True}, "leg": "original"}
        if i:
            turn["reply_to"] = {"turn_id": "test:t%02d" % (i - 1), "index": i - 1, "speaker": seats[i - 1]}
        conv["turns"].append(turn)
    conv["timing"]["mainline_turn_budget"] = len(texts)
    return conv, config, list(zip(seats, texts))


class Writer:
    def __init__(self, factory=None):
        self.requests = []
        self.factory = factory
    async def __call__(self, request):
        self.requests.append(copy.deepcopy(request))
        answer = (self.factory(request) if self.factory else
                  "That camera has finally found its audience: an empty platform with excellent patience.")
        request["writing_receipt"] = {"prompt": "actual prompt %s" % request["mode"],
            "raw_result": answer, "clean_result": answer, "requested_chars": request["char_budget"]}
        return answer


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_gate_survivors_keep_original_ids_and_dice(self):
        first = "The photograph vanished from the gallery table before lunch."
        conv, config, rows = fixture([first, first,
            "The staff should search the hall for the missing picture.",
            "Tomorrow we can check the manager's delivery receipt."], seats=["A", "B", "A", "B"])
        original = copy.deepcopy(conv["turns"])
        run = system3.gate_open(conv, rows, rewrites=0, visits=0)
        done = system3.gate_close(conv, run)
        self.assertFalse(done["held"], done)
        self.assertEqual(done["counts"]["dropped"], 2)
        final_rows = [(r["seat"], r["text"]) for r in run["rows"] if r["state"] in ("kept", "rewritten")]
        engine.reconcile_copy_gate(conv, final_rows)
        self.assertEqual([t["turn_id"] for t in conv["turns"]], [original[0]["turn_id"], original[3]["turn_id"]])
        self.assertEqual(conv["handoff_gate"]["dropped_turn_ids"], [original[1]["turn_id"], original[2]["turn_id"]])
        result, _ = await self.apply(conv, config, final_rows)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["turn_ids"], [original[0]["turn_id"], original[3]["turn_id"]])
        self.assertEqual(conv["turns"][1]["reply_to"]["turn_id"], original[0]["turn_id"])
        self.assertEqual(conv["turns"][1]["reply_to"]["index"], 0)
        self.assertTrue(conv["turns"][1]["length_trace"]["reanchor"])

    async def test_copy_gate_does_not_excuse_unrecorded_missing_turns(self):
        conv, config, rows = fixture(["One photograph is missing.", "We should check the wall.",
            "The frame arrived yesterday.", "That receipt gives us a lead."], seats=["A", "B", "A", "B"])
        conv["turn_gate"] = {"turns": [{"turn_id": conv["turns"][1]["turn_id"],
                                        "turn": 1, "state": "dropped"}]}
        before = copy.deepcopy(conv)
        with self.assertRaisesRegex(ValueError, "copy-gate survivors"):
            engine.reconcile_copy_gate(conv, [rows[0], rows[3]])
        self.assertEqual(conv, before)

    async def test_legacy_gate_receipt_reconciles_only_explicit_drops(self):
        conv, _config, rows = fixture(["One photograph is missing.", "We should check the wall.",
            "The frame arrived yesterday.", "That receipt gives us a lead."], seats=["A", "B", "A", "B"])
        conv["turn_gate"] = {"turns": [{"turn_id": conv["turns"][i]["turn_id"],
                                        "turn": i, "state": "dropped"} for i in (1, 2)]}
        engine.reconcile_copy_gate(conv, [rows[0], rows[3]])
        self.assertEqual(len(conv["turns"]), 2)

    async def test_copy_gate_identity_mismatch_is_refused(self):
        conv, _config, rows = fixture(["One photograph is missing.", "We should check the wall.",
            "The frame arrived yesterday.", "That receipt gives us a lead."], seats=["A", "B", "A", "B"])
        conv["turn_gate"] = {"turns": [{"turn_id": conv["turns"][i]["turn_id"],
                                        "turn": i, "state": "dropped"} for i in (1, 2)],
                             "output_turn_ids": [conv["turns"][0]["turn_id"], "unplanned:turn"]}
        with self.assertRaisesRegex(ValueError, "approved turn identities"):
            engine.reconcile_copy_gate(conv, [rows[0], rows[3]])

    async def apply(self, conv, config, rows, writer=None, people=None):
        writer = writer or Writer()
        result = await engine.finalize_exchange(conv, config, rows, PEOPLE if people is None else people, writer, kind="gallery")
        return result, writer

    async def test_respond_handoff_preserves_original_ids_and_fresh_direction(self):
        source = long_text()
        conv, config, rows = fixture([source])
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual("ready", result["status"])
        self.assertEqual("ready", conv["handoff"]["status"])
        self.assertEqual(2, len(result["rows"]))
        self.assertEqual(["test:t00"], result["original_turn_ids"])
        self.assertTrue(result["turn_ids"][1].startswith("test:t00h"))
        child = conv["turns"][1]
        self.assertNotEqual("A", child["speaker"])
        self.assertEqual("test:t00", child["reply_to"]["turn_id"])
        self.assertEqual(0, child["reply_to"]["index"])
        self.assertFalse(any(k in child for k in ("protocol", "leg", "place")))
        self.assertNotEqual({"original": True}, child["performance"])
        self.assertEqual({"ES", "RS"}, {d["family"] for d in child["decisions"] if d["family"] != "HANDOFF"})
        self.assertEqual("respond", writer.requests[0]["mode"])
        self.assertEqual(result["rows"][0][1], writer.requests[0]["preceding_text"])
        self.assertGreater(conv["turns"][0]["length_trace"]["dropped_chars"], 0)
        self.assertEqual("actual prompt respond", child["handoff_writing"][0]["prompt"])
        self.assertEqual(1, conv["handoff"]["extra_turns"])

    async def test_carry_mode_uses_remaining_ideas_with_bounded_children(self):
        conv, config, rows = fixture([long_text(30)], policy={"respond_probability": 0.})
        writer = Writer(lambda r: r["remaining_ideas"] if r["mode"] == "carry" else
                        "The framing changes once the conversation reaches the actual photograph.")
        result, _ = await self.apply(conv, config, rows, writer)
        self.assertEqual(4, len(result["rows"]))
        self.assertEqual(3, conv["handoff"]["extra_turns"])
        self.assertEqual(["carry"] * 3, [r["mode"] for r in writer.requests])
        self.assertTrue(all(len(text) <= 800 for _, text in result["rows"]))
        self.assertTrue(all(t["handoff_mode"] == "carry" for t in conv["turns"][1:]))

    async def test_continue_checked_at_each_sentence_and_hard_force(self):
        source = long_text(20)
        conv, config, rows = fixture([source], policy={"continue_probability": 1., "max_extra_turns": 0})
        result, writer = await self.apply(conv, config, rows)
        checkpoints = conv["turns"][0]["length_trace"]["checkpoints"]
        self.assertGreater(len(checkpoints), 2)
        self.assertTrue(all(c["outcome"] == "CONTINUE" for c in checkpoints[:-1]))
        self.assertEqual("HANDOFF", checkpoints[-1]["outcome"])
        self.assertTrue(checkpoints[-1]["forced"])
        self.assertGreaterEqual(checkpoints[-1]["offset"], 800)
        self.assertLessEqual(len(result["rows"][0][1]), 800)
        self.assertFalse(writer.requests)
        self.assertEqual("budget_shortened", conv["turns"][0]["length_trace"]["status"])

    async def test_long_single_sentence_is_bounded(self):
        source = " ".join(["The platform camera finds another peculiar angle"] * 35)
        conv, config, rows = fixture([source], policy={"max_extra_turns": 0})
        result, _ = await self.apply(conv, config, rows)
        self.assertLessEqual(len(result["rows"][0][1]), 800)
        self.assertTrue(result["rows"][0][1].endswith("…"))
        self.assertTrue(conv["turns"][0]["length_trace"]["forced"])

    async def test_no_alternate_shortens_and_reports_exclusions(self):
        conv, config, rows = fixture([long_text()])
        result, writer = await self.apply(conv, config, rows, people=[PEOPLE[0], dict(PEOPLE[1], available=False)])
        self.assertEqual(1, len(result["rows"]))
        self.assertFalse(writer.requests)
        trace = conv["turns"][0]["length_trace"]
        self.assertEqual("no_speaker_shortened", trace["status"])
        event = next(e for e in conv["decision_events"] if e["event_id"] == trace["receipt"])
        self.assertEqual({"current speaker", "not present"}, {x["why"] for x in event["meta"]["excluded"]})

    async def test_zero_weight_speaker_excluded(self):
        conv, config, rows = fixture([long_text()])
        config["split"]["who"]["cohost"] = 0
        result, _ = await self.apply(conv, config, rows)
        self.assertEqual("D", result["rows"][1][0])
        event = next(e for e in conv["decision_events"] if e["meta"].get("kind") == "speaker")
        self.assertTrue(any(x["id"] == "B" for x in event["stages"][0]["excluded"]))

    async def test_conversation_budget_counts_prior_extra(self):
        conv, config, rows = fixture([long_text()], policy={"max_extra_turns": 1})
        conv["turns"][0]["split_of"] = "prior:t00"
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual(1, len(result["rows"]))
        self.assertEqual(1, conv["handoff"]["extra_turns"])
        self.assertFalse(writer.requests)

    async def test_explicit_exact_copy_preserved_with_receipt(self):
        source = long_text(20)
        for flag in ("read_exactly", "protected_copy", "handoff_protected"):
            conv, config, rows = fixture([source])
            conv["turns"][0][flag] = True
            result, writer = await self.apply(conv, config, rows)
            self.assertEqual(rows, result["rows"])
            self.assertFalse(writer.requests)
            self.assertEqual("protected_copy", conv["turns"][0]["length_trace"]["status"])
            self.assertTrue(conv["turns"][0]["length_trace"]["receipt"])

    async def test_writer_actual_char_limit_and_receipts(self):
        conv, config, rows = fixture([long_text()])
        writer = Writer(lambda r: "A fresh objection comes from the other side of the studio. " * 20)
        result, _ = await self.apply(conv, config, rows, writer)
        self.assertLessEqual(len(result["rows"][1][1]), 250)
        receipt = conv["turns"][1]["handoff"]["writer_attempts"][0]
        self.assertGreater(receipt["chars"], receipt["kept_chars"])
        self.assertIn("raw_result", receipt["writing_receipt"])

    async def test_generated_exact_copy_retries_then_shortens(self):
        conv, config, rows = fixture([long_text()])
        writer = Writer(lambda r: r["preceding_text"])
        original_actor_state = copy.deepcopy(conv["participants"])
        result, _ = await self.apply(conv, config, rows, writer)
        self.assertEqual(original_actor_state, conv["participants"])
        self.assertEqual(2, len(writer.requests))
        self.assertEqual(1, len(result["rows"]))
        self.assertEqual("writer_failed_shortened", conv["turns"][0]["length_trace"]["status"])
        self.assertTrue(all(a["rejection"] for a in conv["turns"][0]["length_trace"]["insertions"][0]["attempts"]))

    async def test_mainline_exact_duplicate_repaired_same_actor_no_extra(self):
        text = "The station windows make this particular photograph look unusually lonely."
        conv, config, rows = fixture([text, text], seats=["A", "B"])
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual(2, len(result["rows"]))
        self.assertEqual("B", writer.requests[0]["seat"])
        self.assertEqual("repair_duplicate", writer.requests[0]["mode"])
        self.assertNotEqual(result["rows"][0][1], result["rows"][1][1])
        self.assertEqual(0, conv["handoff"]["extra_turns"])
        self.assertIn("duplicate_repair", conv["turns"][1]["length_trace"])
        self.assertFalse(any(e["meta"].get("kind") in ("speaker", "mode") for e in conv["decision_events"]))

    async def test_failed_mainline_duplicate_refuses_candidate(self):
        text = "The station windows make this particular photograph look unusually lonely."
        conv, config, rows = fixture([text, text], seats=["A", "B"])
        writer = Writer(lambda r: text)
        with self.assertRaisesRegex(ValueError, "duplicate dialogue repair failed"):
            await self.apply(conv, config, rows, writer)
        self.assertEqual(2, len(writer.requests))
        self.assertNotIn("handoff", conv)

    async def test_repeated_sentence_caught_and_deliberate_short_quote_allowed(self):
        line = "Those station windows make the photograph look unusually lonely."
        self.assertTrue(engine._duplicate_reason(line + " Another thought joins it.", [line]))
        self.assertFalse(engine._duplicate_reason('"' + line + '" That is why I charged the camera rent.', [line]))
        self.assertTrue(engine._duplicate_reason(line, [line]))

    async def test_reanchor_uses_actual_transcript_and_keeps_closing(self):
        conv, config, rows = fixture([long_text(), "Those omitted photographs prove that the camera was defective.",
                                      "Thank you for calling. We will get that request on the air."],
                                     seats=["A", "B", "A"])
        conv["turns"][2]["handoff_protected"] = "required caller resolution"
        writer = Writer(lambda r: "The light across those empty windows makes the platform feel like a stage." if r["mode"] == "respond"
                        else "That framing tells us more about the quiet platform than about the camera.")
        result, _ = await self.apply(conv, config, rows, writer)
        self.assertEqual(["respond", "reanchor"], [r["mode"] for r in writer.requests])
        request = writer.requests[1]
        self.assertEqual(result["rows"][1][1], request["preceding_text"])
        self.assertEqual(result["rows"][0][1], request["target_text"])
        self.assertEqual("B", request["seat"])
        self.assertEqual(rows[-1], result["rows"][-1])
        self.assertEqual(["test:t00", "test:t01", "test:t02"],
                         [t["turn_id"] for t in conv["turns"] if not t.get("handoff_parent")])
        self.assertEqual(2, conv["turns"][-1]["reply_to"]["index"])
        self.assertIn("reanchor", conv["turns"][2]["length_trace"])

    async def test_reanchor_failure_refuses_unheard_source_assumptions(self):
        conv, config, rows = fixture([long_text(), "The omitted tail is the whole reason for my reply."], seats=["A", "B"])
        writer = Writer(lambda r: "Another actor finds a sharper angle on the studio lighting." if r["mode"] == "respond" else "")
        with self.assertRaisesRegex(ValueError, "dialogue reanchor failed"):
            await self.apply(conv, config, rows, writer)

    async def test_idempotent_retry_has_no_new_draws_or_writer_calls(self):
        conv, config, rows = fixture([long_text()])
        result, writer = await self.apply(conv, config, rows)
        events, draws, requests = len(conv["decision_events"]), conv["handoff_draws"], len(writer.requests)
        again, _ = await self.apply(conv, config, result["rows"], writer)
        self.assertEqual(result["rows"], again["rows"])
        self.assertFalse(again["changed"])
        self.assertEqual((events, draws, requests), (len(conv["decision_events"]), conv["handoff_draws"], len(writer.requests)))

    async def test_seeded_candidates_and_rng_replay(self):
        results, events = [], []
        for _ in range(2):
            conv, config, rows = fixture([long_text()])
            result, _ = await self.apply(conv, config, rows)
            results.append(result["rows"])
            events.append([(e["family"], e["selected"], e.get("rng"), e["stages"]) for e in conv["decision_events"]])
        self.assertEqual(results[0], results[1])
        self.assertEqual(events[0], events[1])
        handoff = [e for e in conv["decision_events"] if e["family"] == "HANDOFF"]
        self.assertTrue(any(e["stages"][0].get("candidates") for e in handoff))
        self.assertTrue(all(e.get("rng") for e in handoff if e["meta"].get("kind") in ("threshold", "speaker", "mode")))

    async def test_threshold_is_once_per_turn_and_space_counted(self):
        source = " " * 100 + long_text(4)
        conv, config, rows = fixture([source], policy={"thresholds": [250, 350, 450, 550]})
        result, _ = await self.apply(conv, config, rows)
        for turn in conv["turns"]:
            threshold = [e for e in conv["decision_events"] if e["turn_id"] == turn["turn_id"] and e["meta"].get("kind") == "threshold"]
            self.assertEqual(1, len(threshold))
            self.assertEqual(4, len(threshold[0]["stages"][0]["candidates"]))
            self.assertIn(turn["length_trace"]["threshold"], [250, 350, 450, 550])
            self.assertEqual(len(turn["text"]), turn["length_trace"]["final_chars"])

    async def test_disabled_receipt_and_config_hash_are_pinned(self):
        conv, config, rows = fixture([long_text()])
        old_hash = system3.config_hash(config)
        config["handoff"]["enabled"] = False
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual("disabled", result["status"])
        self.assertEqual("disabled", conv["handoff"]["status"])
        self.assertEqual(rows, result["rows"])
        self.assertFalse(writer.requests)
        self.assertEqual(engine.policy_hash(config), conv["handoff"]["policy_hash"])
        self.assertNotEqual(old_hash, system3.config_hash(config))
        again, _ = await self.apply(conv, config, result["rows"], writer)
        self.assertEqual("disabled", again["status"])
        self.assertFalse(again["changed"])


    async def test_original_source_retry_reuses_expanded_cached_output(self):
        conv, config, rows = fixture([long_text()])
        result, writer = await self.apply(conv, config, rows)
        events, draws, requests = len(conv["decision_events"]), conv["handoff_draws"], len(writer.requests)
        retry, _ = await self.apply(conv, config, rows, writer)
        self.assertEqual(result["rows"], retry["rows"])
        self.assertEqual(["test:t00"], retry["original_turn_ids"])
        self.assertEqual(result["turn_ids"], retry["turn_ids"])
        self.assertTrue(retry["changed"])
        self.assertEqual(engine.policy_hash(config), retry["policy_hash"])
        self.assertEqual((events, draws, requests), (len(conv["decision_events"]), conv["handoff_draws"], len(writer.requests)))

    async def test_disabled_length_still_repairs_exact_copies_without_rng(self):
        text = "The station windows make this particular photograph look unusually lonely."
        conv, config, rows = fixture([text, text], seats=["A", "B"], policy={"enabled": False})
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual("disabled", result["status"])
        self.assertEqual("repair_duplicate", writer.requests[0]["mode"])
        self.assertNotEqual(result["rows"][0][1], result["rows"][1][1])
        self.assertEqual(0, conv["handoff_draws"])
        self.assertTrue(all(e.get("rng") is None for e in conv["decision_events"]))
        self.assertTrue(all(t["length_trace"]["threshold"] is None for t in conv["turns"]))
        self.assertEqual(2, len(conv["turns"]))


    async def test_structured_mandatory_closing_rewritten_in_place_and_kept_last(self):
        for annotation in ({"graph_type": "end"}, {"place": "close"},
                           {"decisions": [{"family": "FL", "item": "fl-close", "text": "Return to the music"}]}):
            conv, config, rows = fixture(["A short opening thought.", long_text() + " Thank you; back to the music."],
                                         seats=["A", "B"])
            conv["turns"][-1].update(annotation)
            writer = Writer(lambda r: "Thank you for the photographs. Back to the music.")
            result, _ = await self.apply(conv, config, rows, writer)
            self.assertEqual(2, len(result["rows"]))
            self.assertEqual("test:t01", result["turn_ids"][-1])
            self.assertEqual("shorten", writer.requests[0]["mode"])
            self.assertTrue(writer.requests[0]["mandatory_closing"])
            self.assertEqual(0, conv["handoff"]["extra_turns"])
            self.assertLessEqual(len(result["rows"][-1][1]), 250)
            self.assertTrue(conv["turns"][-1]["length_trace"]["closing_kept_last"])
            self.assertIn("closing_shorten", conv["turns"][-1]["length_trace"])

    async def test_failed_mandatory_closing_refuses_candidate(self):
        conv, config, rows = fixture([long_text()])
        conv["turns"][0]["graph_type"] = "end"
        with self.assertRaisesRegex(ValueError, "mandatory closing shortening failed"):
            await self.apply(conv, config, rows, Writer(lambda r: ""))


    async def test_real_single_plan_line_opening_can_handoff_with_fresh_child_voices(self):
        _unused, config, _rows = fixture([long_text(30)], policy={"respond_probability": 0.})
        inputs = {"road": "ad_spot", "seats": ["A"], "names": {"A": "Dill"}, "roles": {"A": "dj"},
                  "turns": 1, "subject": {"topic": "the gallery"}, "availability": {}}
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}),
                                       seed="single-opening", conversation_id="single-opening")
        system3.plan_line(conv, config, inputs)
        self.assertEqual(1, len(conv["turns"]))
        self.assertEqual("close", conv["turns"][0]["place"])
        conv["turns"][0]["handoff_opening"] = True
        conv["timing"]["mainline_turn_budget"] = 1
        writer = Writer(lambda r: r["remaining_ideas"])
        result, _ = await self.apply(conv, config, [("A", long_text(30))], writer)
        self.assertEqual(4, len(result["rows"]))
        self.assertEqual(3, conv["handoff"]["extra_turns"])
        self.assertNotEqual("A", result["rows"][1][0])
        self.assertTrue(all(t.get("handoff_parent") for t in conv["turns"][1:]))
        self.assertTrue(all(not t.get("protocol") for t in conv["turns"][1:]))
        self.assertTrue(all(t.get("performance") for t in conv["turns"][1:]))
        self.assertTrue(all({d["family"] for d in t["decisions"]} >= {"ES", "RS"} for t in conv["turns"][1:]))


    async def test_implicit_fl_singleton_is_eligible_but_explicit_endpoint_is_preserved(self):
        conv, config, rows = fixture([long_text()])
        conv["turns"][0]["decisions"] = [{"family": "FL", "item": "fl-close"}]
        result, _ = await self.apply(conv, config, rows)
        self.assertGreater(len(result["rows"]), 1)
        conv, config, rows = fixture([long_text()])
        conv["turns"][0].update(handoff_opening=True, graph_type="end", place="close")
        result, writer = await self.apply(conv, config, rows)
        self.assertEqual(1, len(result["rows"]))
        self.assertEqual("shorten", writer.requests[0]["mode"])
        self.assertTrue(conv["turns"][0]["length_trace"]["closing_kept_last"])

    async def test_alignment_is_required(self):
        conv, config, rows = fixture(["A short line."])
        with self.assertRaisesRegex(ValueError, "align"):
            await self.apply(conv, config, [("B", rows[0][1])])


class PolicyTests(unittest.TestCase):
    def test_defaults_and_bounded_validation(self):
        self.assertEqual([250, 350, 450, 550], engine.config_of({})["thresholds"])
        self.assertTrue(engine.config_of({})["enabled"])
        for bad in ({"thresholds": [250, 250]}, {"thresholds": [250.5]}, {"hard_chars": 200},
                    {"continue_probability": float("nan")}, {"max_extra_turns": -1}, {"writer_retries": 4}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                engine.validate_config(bad)


if __name__ == "__main__":
    unittest.main()

