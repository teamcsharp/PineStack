"""2026-09-08: "I want a button to accept what I type and to send it through
auto approved. I want to be able to correct the lines and assist the
algorithm with how to behave." The operator's wording goes through with the
operator's authority; the machine report is recorded, never a gate; the
instruction becomes a standing lesson for lines of this kind."""
import unittest

from test_rejection_workbench import WorkbenchTests


class AcceptAsWrittenTests(WorkbenchTests):
    async def test_the_operators_wording_is_applied_whatever_the_machine_says(self):
        refused = {'ok': False, 'machine_ok': False, 'faults': ['rhetoric was not materially transformed'],
                   'machine_faults': ['rhetoric was not materially transformed']}
        self.host['tint_evaluate'].side_effect = lambda *args, **kw: (self.assertTrue(self.preview.get()), refused)[1]
        wording = 'The red door creaks at night / and wakes the hall in fright.'
        response = await self.request('POST', 'accept', self.body('accept-fixture-1', candidate=wording,
                                                                   instruction='Let a light touch stand when it lands a rhyme.'))
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        op = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(op['status'], 'completed', op)
        self.assertFalse(op['result']['machine_ok'])
        self.assertIn('Approved as written', op['result']['say'])
        self.assertIn('standing lesson', op['result']['say'])
        # The line is allowed with the operator's wording, and recovery got exactly that wording.
        row = self.reviews.get(self.row['id'])
        self.assertEqual(row['review_status'], 'allowed')
        self.assertEqual(row['decision']['basis'], 'accepted_as_written')
        self.assertEqual(row['decision']['wording'], wording)
        self.assertEqual(row['decision']['note'], 'Let a light touch stand when it lands a rhyme.')
        instance = self.host['line_review_recover'].call_args.args[0]
        self.assertEqual(instance['candidate'], wording)
        self.assertEqual(instance['evaluation']['by'], 'operator')
        self.assertFalse(instance['evaluation']['machine_ok'])
        # The wording and the instruction are now a preference example for banter lines.
        examples = self.reviews.preference_examples(kind='banter', gate='tint')
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]['candidate'], wording)
        self.assertEqual(examples[0]['note'], 'Let a light touch stand when it lands a rhyme.')
        self.assertTrue(examples[0]['by_operator'])
        # ...and the pair is approved outright: the gate never refuses it again.
        self.assertTrue(self.reviews.evaluate('tint', self.source, wording, ['style'],
                                              context={'kind': 'banter', 'marker': 'A'})['allowed'])
        self.assertFalse(self.reviews.evaluate('tint', self.source, self.candidate, ['style'],
                                               context={'kind': 'banter', 'marker': 'A'})['allowed'])
        # The trial receipt keeps the machine's view for the record.
        trials = self.store.history(self.row['id'], self.row['event_seq'], 'trials')['items']
        self.assertEqual(trials[0]['provenance']['origin'], 'operator_accept')
        self.assertEqual(trials[0]['evaluation']['machine_faults'], ['rhetoric was not materially transformed'])

    async def test_an_empty_wording_or_no_auth_is_refused(self):
        response = await self.request('POST', 'accept', self.body('accept-fixture-2', candidate='   '))
        self.assertEqual(response.status_code, 400, response.text)
        response = await self.request('POST', 'accept', self.body('accept-fixture-3', candidate='x'), auth=False)
        self.assertEqual(response.status_code, 401, response.text)
        self.host['line_review_recover'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
