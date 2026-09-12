"""Measured no-progress repair waits preserve originals and yield other work."""
import asyncio
import copy
import json
import unittest
from contextlib import ExitStack
from unittest import mock

import app
import test_crystal_model_output as adapter_fixture


class TintRetryBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = self.stack = ExitStack(); self.addCleanup(stack.close)
        self.now = 10000.0; self.context = 'same-context'
        self.real_context = app._tint_retry_context
        values = {'time.time': lambda:self.now,
                  '_tint_retry_context': lambda entry,kind:self.context,
                  'dialogue_tint_required': lambda:True,
                  'legacy_tint_revalidate': mock.AsyncMock(),
                  '_larder_current': lambda entry:False,
                  'tint_coverage_ready': lambda evidence:False,
                  '_pantry_save': mock.Mock(), '_larder_save':mock.Mock(),
                  '_tint_paper': lambda result,**kwargs:copy.deepcopy(result),
                  'pipeline_log':mock.Mock()}
        for name,value in values.items():
            if name=='time.time':stack.enter_context(mock.patch.object(app.time,'time',value))
            else:stack.enter_context(mock.patch.object(app,name,value))
        self.progress={'source':'retained','turns':[
            {'source':str(i),'marker':'A','selected':True,'text':f'Accepted original {i}.',
             'evaluation':{'ok':True}} for i in range(20)] +
            [{'source':'20','marker':'B','selected':True,'text':'','rejected_candidate':'Preserved failed words',
              'evaluation':{'ok':False,'faults':['no rhyme evidence']}}]}
        self.entry={'script':'A: Original first.\nB: Original last.',
            'script_plain':'A: Original first.\nB: Original last.',
            'prep_kind':'caller','caller_name':'Fixture','caller_voice':'fixture-voice',
            'call':{'quality':{'ok':True,'operator_accepted':True}},
            'keys':['untouched-media'], 'tint_progress':copy.deepcopy(self.progress),
            'tint':{'coverage':{'version':4,'accepted':20}},
            'tint_revalidation':{'state':'repair_required'}}
        async def generated(*args,**kwargs):
            app._TINT_REPAIR_RESPONSES.get().extend([True]*4)
            return {'ok':False,'coverage':{'accepted':20,'version':4},
                    'progress':copy.deepcopy(self.progress)}
        self.writer=stack.enter_context(mock.patch.object(app,'crystal_tint',new=mock.AsyncMock(side_effect=generated)))

    async def test_completed_no_progress_wait_does_not_revisit_or_discard_approved_work(self):
        before=copy.deepcopy(self.entry)
        self.assertFalse(await app.ensure_entry_tinted(self.entry,'caller'))
        status=app.tint_retry_status(self.entry,'caller')
        self.assertTrue(status['waiting']);self.assertEqual(status['remaining_seconds'],300)
        self.assertEqual(status['total_model_responses'],4)
        self.assertEqual(status['accepted_highwater'],20)
        self.assertEqual(status['blocking_faults'],['no rhyme evidence'])
        self.assertFalse(await app.ensure_entry_tinted(self.entry,'caller'))
        self.writer.assert_awaited_once()
        for key in ('script','script_plain','call','keys','tint_progress'):
            self.assertEqual(self.entry[key],before[key])
        restored=json.loads(json.dumps(self.entry))
        self.assertTrue(app.tint_retry_status(restored,'caller')['waiting'])

    async def test_wait_expires_then_backoff_increases_without_reset_by_changed_candidate(self):
        await app.ensure_entry_tinted(self.entry,'caller')
        self.progress['turns'][-1]['rejected_candidate']='Different failed candidate'
        self.now+=301
        await app.ensure_entry_tinted(self.entry,'caller')
        self.assertEqual(self.writer.await_count,2)
        self.assertEqual(app.tint_retry_status(self.entry,'caller')['remaining_seconds'],600)
        for _ in range(5):
            self.now+=1801
            await app.ensure_entry_tinted(self.entry,'caller')
        # #1082: twelve answers without one more accepted bar strike the line
        # out. The ladder's clock runs out, the strike holds, and nothing is
        # asked again - the writer saw three passes, not seven.
        status=app.tint_retry_status(self.entry,'caller')
        self.assertEqual(self.writer.await_count,3)
        self.assertTrue(status['exhausted']);self.assertTrue(status['waiting'])
        self.assertEqual(status['strikes'],12);self.assertEqual(status['release_reason'],'')

    async def test_more_accepted_turns_clear_stagnation_and_wait(self):
        await app.ensure_entry_tinted(self.entry,'caller')
        self.now+=301
        self.progress['turns'][-1].update(text='Accepted last.',evaluation={'ok':True})
        async def improved(*args,**kwargs):
            app._TINT_REPAIR_RESPONSES.get().append(True)
            return {'ok':False,'coverage':{'accepted':21},'progress':copy.deepcopy(self.progress)}
        self.writer.side_effect=improved
        await app.ensure_entry_tinted(self.entry,'caller')
        state=app.tint_retry_status(self.entry,'caller')
        self.assertFalse(state['waiting']);self.assertEqual(state['accepted_highwater'],21)
        self.assertEqual(state['stagnant_model_responses'],0)

    async def test_relevant_context_or_explicit_review_releases_wait(self):
        await app.ensure_entry_tinted(self.entry,'caller')
        self.context='new-prompt'
        self.assertEqual(app.tint_retry_status(self.entry,'caller')['release_reason'],'context_changed')
        await app.ensure_entry_tinted(self.entry,'caller')
        self.assertEqual(self.writer.await_count,2)
        self.entry['review_recovery_pending']=True
        self.assertFalse(app.tint_retry_status(self.entry,'caller')['waiting'])
        await app.ensure_entry_tinted(self.entry,'caller')
        self.assertEqual(self.writer.await_count,3)

    async def test_zero_work_admission_deferral_never_spends_budget(self):
        self.writer.side_effect=None
        self.writer.return_value={'ok':False,'deferred':True,'progress':copy.deepcopy(self.progress)}
        await app.ensure_entry_tinted(self.entry,'caller')
        self.assertNotIn('tint_retry_budget',self.entry)
        self.assertEqual(self.entry['tint_progress'],self.progress)

    async def test_partial_work_then_deferral_retains_progress_and_counts_only_real_responses(self):
        async def partial(*args,**kwargs):
            app._TINT_REPAIR_RESPONSES.get().extend([True]*4)
            return {'ok':False,'deferred':True,'progress':copy.deepcopy(self.progress)}
        self.writer.side_effect=partial
        await app.ensure_entry_tinted(self.entry,'caller')
        self.assertTrue(app.tint_retry_status(self.entry,'caller')['waiting'])
        self.assertEqual(self.entry['tint_progress'],self.progress)

    async def test_recovery_selector_skips_waiting_parent_and_visits_another(self):
        await app.ensure_entry_tinted(self.entry,'caller')
        other=copy.deepcopy(self.entry);other.pop('tint_retry_budget');other['tint_tried']=0
        other['tint_revalidation']={'state':'repair_required'}
        helper=mock.AsyncMock(return_value=False)
        values={'_RADIO':{'on':True},'prepared_seconds':lambda:10000,
            '_LARDER_WRITING':[False],'tint_should_stop':lambda **kw:'',
            'writing_room_state':lambda:{'jobs':[]},'committed_stock_ids':lambda **kw:set(),
            'tint_recovery_rows':lambda:[('caller',self.entry),('caller',other)],
            'dialogue_entry':lambda row:row,'dialogue_tint_ready':lambda *args:False,
            'dialogue_row_viable':lambda *args:True,'alt_sid':lambda kind,row:str(id(row)),
            'ensure_shelf_row_tinted':helper,'_TINT_RECOVERY_STATE':{}}
        with ExitStack() as stack:
            for name,value in values.items():stack.enter_context(mock.patch.object(app,name,value))
            await app.tint_recovery_step()
        helper.assert_awaited_once_with('caller',other,critical=True)
        self.assertTrue(app.tint_retry_status(self.entry,'caller')['waiting'])

    def test_global_other_road_revision_does_not_release_this_roads_wait(self):
        guidance=('OBSERVED REWRITE LESSONS (learning revision 2). These evidence-guided recipes '
                  'do not relax meaning, rhyme, speaker or technical requirements:\n- Current caller recipe')
        selection={'strategy_ids':['caller:rhyme:v1'],'guidance':guidance,'learning_revision':2}
        values={'_larder_profile_signature':lambda:'profile','tint_model_for':lambda kind:'model',
                'crystal_active':lambda:[], 'crystal_force':lambda:.88,
                'crystal_grade_strict':lambda:False,'crystal_coverage_target':lambda:100}
        with ExitStack() as stack:
            for name,value in values.items():stack.enter_context(mock.patch.object(app,name,value))
            stack.enter_context(mock.patch.object(app._PROMPT_LEARNING,'selection',side_effect=lambda kind:dict(selection)))
            first=self.real_context(self.entry,'caller')
            selection['learning_revision']=3
            selection['guidance']=guidance.replace('revision 2)', 'revision 3)')
            self.assertEqual(self.real_context(self.entry,'caller'),first)
            selection['guidance']=selection['guidance'].replace('Current caller recipe','New caller recipe')
            self.assertNotEqual(self.real_context(self.entry,'caller'),first)
            selection['guidance']=guidance
            selection['strategy_ids']=['caller:rhyme:v2']
            self.assertNotEqual(self.real_context(self.entry,'caller'),first)


class ActualResponseScopeTests(unittest.IsolatedAsyncioTestCase):
    setUp=adapter_fixture.CrystalModelOutputTests.setUp

    async def test_child_response_is_counted_but_admission_and_other_writing_are_not(self):
        responses=[];token=app._TINT_REPAIR_RESPONSES.set(responses)
        try:
            self.call.return_value={'message':{'content':'The light is near / the source is clear.'},'done_reason':'stop'}
            await asyncio.create_task(app.ask_model('Tint.',mark={'kind':'tint round'}))
            await app.ask_model('Ordinary prose.')
            self.call.return_value={'deferred':True,'reason':'lane full'}
            with self.assertRaises(app.WritingDeferred):
                await app.ask_model('Tint.',mark={'kind':'tint round'})
            self.assertEqual(responses,[True])
        finally:
            app._TINT_REPAIR_RESPONSES.reset(token)
        self.assertIsNone(app._TINT_REPAIR_RESPONSES.get())


if __name__=='__main__':
    unittest.main()
