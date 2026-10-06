"""Inspect actual model prompts rather than merely recovery descriptors."""
import copy
import unittest

import handoff_preparation as hp


class DialogueRepairPromptTests(unittest.IsolatedAsyncioTestCase):
    def request(self, seed="one", level=0):
        return {"mode": "recover_exchange", "char_budget": 450,
            "recovery": {"seed": seed, "variation_id": seed, "operation": "rewrite", "style_level": level},
            "planned_turns": [{"turn_id": "p", "speaker": "A", "name": "Dill", "step": "open",
                "directions": "Answer the gallery question. Use dense rhyme and ornate cadence."},
                {"turn_id": "q", "speaker": "B", "name": "Skip", "step": "close", "mandatory_closing": True}],
            "preserved_rows": [{"turn_id": "p", "speaker": "A", "index": 0, "text": "The gallery opens Friday."}],
            "subject": {"topic": "the gallery", "sources": ["brief"]},
            "participants": [{"actor_id": "A", "name": "Dill", "role": "dj"},
                {"actor_id": "B", "name": "Skip", "role": "cohost"}],
            "source_rows": [("A", "The gallery opens Friday.")], "source_context": {},
            "rejection": "final rows did not align"}

    async def write(self, request, raw="A: The gallery opens Friday.\nB: Shall we check the frames?"):
        received = []
        async def ask(prompt, **kwargs):
            received.append((prompt, kwargs))
            return raw
        result = await hp.write_turn(request, ask, str.strip)
        return result, received

    async def test_whole_exchange_uses_one_model_call_and_keeps_marker_lines(self):
        request = self.request()
        output, received = await self.write(request)
        self.assertEqual(len(received), 1)
        self.assertEqual(output.splitlines(), ["A: The gallery opens Friday.", "B: Shall we check the frames?"])
        self.assertIn("exactly 2 dialogue lines", received[0][0])
        self.assertIn("IMMUTABLE IDENTIFIED TURNS", received[0][0])
        self.assertEqual(received[0][1]["result_contract"], "structured_turns")
        self.assertEqual(request["writing_receipt"]["clean_result"], output)
        self.assertEqual(request["writing_receipt"]["recovery"]["seed"], "one")

    async def test_actual_ask_contract_preserves_multiline_exchange_through_adapter(self):
        raw = "A: The gallery opens Friday.\nB: Shall we check the frames?"
        async def ask(prompt, **kwargs):
            # The station's ordinary prose path folds line breaks. A whole
            # exchange must explicitly choose its existing structured path.
            return raw if kwargs.get("result_contract") == "structured_turns" else " ".join(raw.split())
        output = await hp.write_turn(self.request(), ask, str.strip)
        self.assertEqual(output, raw)

    async def test_stale_source_identity_receipt_is_explicit_in_actual_prompt(self):
        request = self.request()
        request["source_rows"].append(("B", "A fact from an old removed leg."))
        request["source_identity_evidence"] = {
            "policy": "Only current identified turns have ownership; stale rows remain unassigned source evidence.",
            "identified_source_turn_ids": ["p"],
            "unassigned_rows": [{"source_index": 1, "source_turn_id": "old-removed", "speaker": "B"}]}
        _output, received = await self.write(request)
        prompt = received[0][0]
        self.assertIn("unassigned source evidence", prompt)
        self.assertIn('"source_index": 1', prompt)
        self.assertIn('"source_turn_id": "old-removed"', prompt)
        self.assertIn("A fact from an old removed leg.", prompt)

    async def test_seed_changes_actual_prompt_order_and_is_replayable(self):
        requests = [self.request(str(i)) for i in range(10)]
        prompts, orders = [], []
        for request in requests:
            _result, received = await self.write(request)
            prompts.append(received[0][0])
            orders.append(tuple(request["writing_receipt"]["recovery"]["order"]))
        self.assertEqual(len(set(prompts)), 10)
        self.assertGreater(len(set(orders)), 1)
        again = self.request("0")
        _result, received = await self.write(again)
        self.assertEqual(received[0][0], prompts[0])

    async def test_relaxation_removes_conflicting_style_direction_but_retains_facts(self):
        request = self.request(level=2)
        _result, received = await self.write(request)
        prompt = received[0][0]
        self.assertNotIn("Use dense rhyme and ornate cadence.", prompt)
        self.assertIn("Answer the gallery question.", prompt)
        self.assertIn("The gallery opens Friday.", prompt)
        self.assertIn("required purpose", prompt)
        self.assertIn("mandatory_closing", prompt)

    async def test_adapter_preserves_bad_explanatory_output_for_strict_rejection(self):
        output, _received = await self.write(self.request(), raw="Here is a script:\nA: First.\nB: Second.")
        self.assertTrue(output.startswith("Here is a script:"))

    async def test_single_turn_also_gets_actual_variation_and_style_receipt(self):
        request = {"mode": "reanchor", "name": "Dill", "directions": "Answer Skip. Use rhyme.",
            "char_budget": 250, "preceding_text": "The frames are missing.",
            "recovery": {"seed": "single", "operation": "reroll", "style_level": 2}}
        output, received = await self.write(request, raw="Dill: Where did those frames go?")
        self.assertEqual(output, "Where did those frames go?")
        self.assertNotIn("Use rhyme.", received[0][0])
        self.assertIn("250 characters", received[0][0])
        self.assertEqual(request["writing_receipt"]["recovery"]["style_level"], 2)

    def test_optional_requirements_relax_in_three_separate_stages(self):
        directions = ["Keep the price at fifty dollars.", "Use rhyme.",
            "Use a minimum length of eighty words.", "Use ornate cadence."]
        first = hp._creative_directions(directions, 1)
        second = hp._creative_directions(directions, 2)
        third = hp._creative_directions(directions, 3)
        self.assertNotIn("Use rhyme.", first)
        self.assertIn("minimum length", first)
        self.assertIn("ornate cadence", first)
        self.assertNotIn("minimum length", second)
        self.assertIn("ornate cadence", second)
        self.assertNotIn("ornate cadence", third)
        self.assertIn("fifty dollars", third)

    def test_mixed_semantic_style_clause_never_loses_source_obligation(self):
        direction = "Keep the price at fifty dollars while choosing a rhyme. Do not invent facts to complete rhyme."
        relaxed = hp._creative_directions(direction, 3)
        self.assertIn("price at fifty dollars", relaxed)
        self.assertIn("Do not invent facts", relaxed)


if __name__ == "__main__":
    unittest.main()
