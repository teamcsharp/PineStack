import json
import unittest
from unittest.mock import AsyncMock
from dialogue_recovery import begin_attempt, failure_feedback, note_deferred, note_failure, note_success, recovery_state
import handoff_preparation as hp


class FailureFeedbackTests(unittest.TestCase):
    def test_observed_validators_have_distinct_repairs(self):
        cases={
            'recovery rows must align with every planned turn':('turn_structure','enforce_turn_contract'),
            'identified recovery output repeats a turn key':('turn_structure','enforce_turn_contract'),
            'recovery output includes unlabelled or empty dialogue':('turn_structure','enforce_turn_contract'),
            'recovery cannot silently discard unplanned dialogue rows':('turn_structure','enforce_turn_contract'),
            'proven recovery source identities changed their planned order':('source_identity','repair_identity_evidence'),
            'a protected turn has no identified exact wording':('source_missing','restore_source'),
            'unwritten required closing did not complete the exchange':('closing','complete_closing'),
            'identified recovery turn exceeds its spoken length budget':('budget','shorten_mutable_copy'),
            'recovery still says a running-order direction aloud':('coherence','rewrite_grounded_copy'),
            'recovery attempt lease expired':('service','recover_service'),
            'unknown refusal':('other','inspect_and_rewrite'),
        }
        for reason,expected in cases.items():
            with self.subTest(reason=reason):
                feedback=failure_feedback('ValueError: '+reason)
                self.assertEqual((feedback['category'],feedback['action']),expected)

    def test_randomization_does_not_claim_to_fix_missing_evidence_or_services(self):
        for reason in ('a protected turn has no identified exact wording',
                       'proven recovery source identities do not match the current plan',
                       'writer connection unavailable'):
            self.assertFalse(failure_feedback(reason)['creative_retry'])

    def test_structural_failures_do_not_relax_creative_requirements(self):
        state=recovery_state({})
        for i in range(8):
            note_failure(state,'recovery rows must align with every planned turn',i)
        self.assertEqual(state['style_level'],0)
        self.assertEqual(state['failure_counts'],{'turn_structure':8})
        self.assertEqual(state['trace'][-1]['action'],'enforce_turn_contract')

    def test_coherence_failures_keep_gradual_style_escalation(self):
        state=recovery_state({})
        for i in range(4):note_failure(state,'recovery copy gate refused: character mismatch',i)
        self.assertEqual(state['style_level'],2)
        self.assertEqual(state['failure_counts'],{'coherence':4})

    def test_deferral_and_stale_workers_do_not_pollute_failure_counts(self):
        state=recovery_state({});first=begin_attempt(state,100)
        note_deferred(state,101,first['variation_id'])
        self.assertEqual(state['failure_counts'],{})
        second=begin_attempt(state,102)
        note_failure(state,'closing failed',103,first['variation_id'])
        self.assertEqual(state['failure_counts'],{})
        note_failure(state,'closing failed',104,second['variation_id'])
        self.assertEqual(state['failure_counts'],{'closing':1})

    def test_success_retains_failure_evidence_but_resets_active_escalation(self):
        state=recovery_state({});attempt=begin_attempt(state,100)
        note_failure(state,'closing failed',101,attempt['variation_id'])
        attempt=begin_attempt(state,102);note_success(state,103,attempt['variation_id'])
        self.assertEqual(state['failure_counts'],{'closing':1})
        self.assertEqual(state['failures'],0)
        self.assertEqual(state['style_level'],0)
        json.dumps(state)

    def test_legacy_state_retains_existing_style_level(self):
        container={'dialogue_recovery':{'failures':20,'style_level':2}}
        state=recovery_state(container)
        note_failure(state,'recovery rows must align with every planned turn',100)
        self.assertEqual(state['style_level'],2)


class WriterFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_rejection_does_not_change_single_turn_output_contract(self):
        request={'mode':'reanchor','seat':'A','turn_id':'fixture',
            'rejection':'recovery rows must align with every planned turn',
            'recovery':{'seed':'fixture','variation_id':'fixture','operation':'rewrite'}}
        ask=AsyncMock(return_value='That follows the earlier point.')
        self.assertEqual(await hp.write_turn(request,ask,str.strip),'That follows the earlier point.')
        prompt=ask.call_args.args[0]
        self.assertIn('For this single-turn repair',prompt)
        self.assertNotIn('Return exactly the mutable turn keys',prompt)
        self.assertNotIn('result_schema',ask.call_args.kwargs)

    async def test_legacy_labelled_exchange_keeps_its_output_contract(self):
        request={'mode':'recover_exchange','planned_turns':[{'turn_id':'fixture','speaker':'A'}],
            'rejection':'recovery rows must align with every planned turn',
            'recovery':{'seed':'fixture','variation_id':'fixture','operation':'rewrite'}}
        ask=AsyncMock(return_value='A: That follows the earlier point.')
        self.assertEqual(await hp.write_turn(request,ask,str.strip),'A: That follows the earlier point.')
        prompt=ask.call_args.args[0]
        self.assertIn('one nonempty labelled dialogue line',prompt)
        self.assertNotIn('Return exactly the mutable turn keys',prompt)
        self.assertEqual(ask.call_args.kwargs['result_contract'],'structured_turns')

    async def test_actual_exchange_prompt_carries_targeted_closing_feedback(self):
        request={'mode':'recover_exchange','identified_output':True,
            'planned_turns':[{'turn_id':'fixture','speaker':'A','mandatory_closing':True}],
            'rejection':'unwritten required closing did not complete the exchange',
            'recovery':{'seed':'fixture','variation_id':'fixture','operation':'rewrite'}}
        ask=AsyncMock(return_value='{"turn_0000":"Let us leave it there."}')
        output=await hp.write_turn(request,ask,str.strip)
        self.assertEqual(output,'A: Let us leave it there.')
        prompt=ask.call_args.args[0]
        self.assertIn('FAILURE CATEGORY: closing',prompt)
        self.assertIn('Complete the assigned final closing',prompt)
        self.assertEqual(request['writing_receipt']['recovery']['repair_action'],'complete_closing')
