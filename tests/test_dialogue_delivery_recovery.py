import asyncio
import copy
import threading
import unittest
from unittest.mock import Mock, AsyncMock, patch
from types import SimpleNamespace

from dialogue_delivery_recovery import delivery_evidence, recover_dialogue_delivery
from station_troubleshoot_runtime import StationTroubleshootRuntime


class DeliveryRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=1000
        self.clock=patch('dialogue_delivery_recovery.time.time', lambda:self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.saved=[]
        self.offloop=[]
        self.clips=[{'url':'/media/a.wav','delivery_id':'first','speech':True,'ts':800000,
                     'broadcast_ms':1500000,'row_id':'cue-a','seconds':10,'system3':{'cid':'plan-a'}},
                    {'url':'/media/b.wav','delivery_id':'last','speech':True,'ts':800001,
                     'broadcast_ms':1510000,'stream':{'rows':[{'id':'cue-b'}],'length':20},
                     'system3':{'cid':'plan-b'}}]
        self.ns={'_RADIO':{'on':True,'voice_clips':copy.deepcopy(self.clips)},
                 'radio_paused':lambda:False,'_listeners_live':lambda:[{'id':'actual-page'}],
                 'page_voice_audible_recent':Mock(return_value=False),'_PAGE_AIR_UNTIL':[1530],
                 '_PAGE_DELIVERIES':{c['delivery_id']:{'delivery_id':c['delivery_id'],'at':800,
                    'speech':True,'state':'received','clip':copy.deepcopy(c),'listeners':{}}
                    for c in self.clips},
                 'page_recovery_read':lambda:copy.deepcopy(self.saved),
                 'page_recovery_write':self.write,'_admission_resolve':self.resolve,
                 'playout_tell':Mock(),'page_recovery_chat_rows':Mock(),
                 'system3_injected_node':Mock(),'_FLOOR_OWNER':{}}
        self.ns['_reply_gap']=SimpleNamespace(_BOOKED={'until':1530,'tail':2},
                                             _LAST_DOOR={'rows':123,'start':1500})
        self.ns['page_feed_append']=self.publish
        self.published=[]

    def write(self, clips):
        self.offloop.append(threading.get_ident())
        self.saved=copy.deepcopy(clips)

    def resolve(self,url):
        self.offloop.append(threading.get_ident())
        return url

    def publish(self,c):
        self.assertTrue(self.saved, 'All dialogue must be checkpointed before cutting the old epoch.')
        self.assertTrue(self.ns['_DIALOGUE_DELIVERY_RECOVERY']['busy'])
        self.assertTrue(c['air_waited'])
        c['broadcast_ms']=int(max(self.now+7,self.ns['_PAGE_AIR_UNTIL'][0])*1000)
        self.ns['_PAGE_AIR_UNTIL'][0]=c['broadcast_ms']/1000+c.get('seconds',20)
        self.published.append(c)
        self.ns['_PAGE_DELIVERIES'][c['delivery_id']]={'delivery_id':c['delivery_id'],
            'at':self.now,'speech':True,'state':'published','clip':c,'listeners':{}}
        return c['delivery_id']

    async def test_reset_preserves_fifo_cues_and_roulette_without_faking_hearing(self):
        result=await recover_dialogue_delivery(self.ns)
        self.assertTrue(result['changed'])
        self.assertTrue(result['pending'])
        self.assertNotIn('verified',result)
        self.assertEqual([c['url'] for c in self.published],[c['url'] for c in self.clips])
        self.assertEqual([c['system3'] for c in self.published],[c['system3'] for c in self.clips])
        self.assertEqual(self.published[0]['row_id'],'cue-a')
        self.assertEqual(self.published[1]['stream']['rows'],[{'id':'cue-b'}])
        self.assertEqual(self.published[0]['broadcast_ms'],1007000)
        self.assertEqual(self.published[1]['broadcast_ms'],1017000)
        self.assertTrue(all(c['ts']>self.ns['_RADIO']['voice_cut_ms'] for c in self.published))
        self.assertTrue(all(c['delivery_id'] not in ('first','last') for c in self.published))
        self.assertTrue(all(c['recovery_owed'] for c in self.saved))
        self.assertNotIn('_DIALOGUE_HEARD',self.ns)
        self.assertTrue(all(i!=threading.get_ident() for i in self.offloop))
        self.assertEqual(self.ns['_reply_gap']._BOOKED,{'until':0.0,'tail':0.0})
        self.assertEqual(self.ns['_reply_gap']._LAST_DOOR,{'rows':None,'start':0.0})

    async def test_active_audio_off_pause_and_absent_listeners_do_not_cut(self):
        for key,value in [('page_voice_audible_recent',lambda **kw:True),
                          ('radio_paused',lambda:True),('_listeners_live',lambda:[])]:
            old=self.ns[key];self.ns[key]=value
            await recover_dialogue_delivery(self.ns)
            self.assertEqual(self.published,[])
            self.assertNotIn('voice_cut_ms',self.ns['_RADIO'])
            self.ns[key]=old
        self.ns['_RADIO']['on']=False
        await recover_dialogue_delivery(self.ns)
        self.assertEqual(self.published,[])

    async def test_checkpoint_failure_cannot_cut_or_discard_inventory(self):
        self.ns['page_recovery_write']=Mock(side_effect=OSError('disk unavailable'))
        with self.assertRaises(OSError):await recover_dialogue_delivery(self.ns)
        self.assertNotIn('voice_cut_ms',self.ns['_RADIO'])
        self.assertFalse(self.ns['_DIALOGUE_DELIVERY_RECOVERY']['busy'])
        self.assertEqual(self.published,[])

    async def test_inventory_race_aborts_cut(self):
        def racing(clips):
            self.write(clips)
            self.ns['_PAGE_DELIVERIES']['new']={'delivery_id':'new','speech':True,'state':'published'}
        self.ns['page_recovery_write']=racing
        result=await recover_dialogue_delivery(self.ns)
        self.assertFalse(result['changed'])
        self.assertNotIn('voice_cut_ms',self.ns['_RADIO'])

    async def test_missing_assets_preserved_but_not_sent_back_as_broken_heads(self):
        self.ns['_admission_resolve']=lambda url:None if 'a.wav' in url else url
        result=await recover_dialogue_delivery(self.ns)
        self.assertEqual(result['republished'],1)
        self.assertEqual(result['preserved'],2)
        self.assertEqual(self.saved[0]['delivery_id'],'first')

    async def test_completed_stored_delivery_never_replayed(self):
        self.saved=copy.deepcopy(self.clips)
        self.ns['_PAGE_DELIVERIES']['first']['state']='ended'
        await recover_dialogue_delivery(self.ns)
        self.assertEqual([c['url'] for c in self.published],['/media/b.wav'])

    async def test_repeated_reset_does_not_multiply_old_occurrences(self):
        await recover_dialogue_delivery(self.ns)
        await recover_dialogue_delivery(self.ns)
        self.assertEqual(len(self.published),2)
        self.now+=100
        await recover_dialogue_delivery(self.ns)
        self.assertEqual(len(self.published),4)
        self.assertEqual(len(self.saved),2)
        self.assertEqual([c['recovery_of_delivery_id'] for c in self.saved],['first','last'])
        self.assertEqual(delivery_evidence(self.ns)['unstarted_deliveries'],2)

    async def test_only_stuck_boot_transport_owner_can_be_cancelled(self):
        for label in ['recording dialogue','preserved page deliveries after reservation repair']:
            task=SimpleNamespace(done=lambda:False,cancel=Mock())
            self.ns['_FLOOR_OWNER']={'label':label,'task':task}
            await recover_dialogue_delivery(self.ns)
            self.assertEqual(task.cancel.call_count,int(label.startswith('preserved')))
            self.now+=100

    async def test_media_admission_refusal_keeps_original_owed(self):
        self.ns['page_feed_append']=Mock(return_value='')
        result=await recover_dialogue_delivery(self.ns)
        self.assertFalse(result['ok'])
        self.assertEqual([c['delivery_id'] for c in self.saved],['first','last'])
        self.ns['page_recovery_chat_rows'].assert_not_called()

    async def test_frozen_positive_volume_reports_do_not_hide_a_wedge(self):
        self.ns['page_voice_audible_recent'].return_value=True
        self.ns['_PAGE_ACK_EVENTS']=[{'event':'playing','progressed':False,
                                     'audible_volume':.4,'at':1000}]
        self.assertTrue((await recover_dialogue_delivery(self.ns))['changed'])

    async def test_advancing_real_receipts_protect_current_audio(self):
        self.ns['_PAGE_ACK_EVENTS']=[{'event':'playing','progressed':True,
                                     'audible_volume':.4,'at':1000,'delivery_id':'first'}]
        self.assertFalse((await recover_dialogue_delivery(self.ns))['changed'])
        self.assertNotIn('voice_cut_ms',self.ns['_RADIO'])

    async def test_non_dialogue_playback_cannot_hide_silent_owed_speech(self):
        self.ns['_PAGE_DELIVERIES']['sting']={'speech':False,'clip':{'video':True}}
        self.ns['_PAGE_ACK_EVENTS']=[{'event':'playing','progressed':True,'audible_volume':1,'at':1000,'delivery_id':'sting'}]
        evidence=delivery_evidence(self.ns)
        self.assertFalse(evidence['page_speech_active'])
        self.assertTrue(evidence['page_audio_active'])
        self.assertTrue((await recover_dialogue_delivery(self.ns))['changed'])

    def test_unknown_or_muted_clip_cannot_claim_active_dialogue(self):
        for e in [{'delivery_id':'unknown'}, {'delivery_id':'first','muted':True}]:
            self.ns['_PAGE_ACK_EVENTS']=[{'event':'playing','progressed':True,'audible_volume':1,'at':1000,**e}]
            self.assertFalse(delivery_evidence(self.ns)['page_speech_active'])


class SilenceWatchdogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=1000
        self.clock=patch('station_troubleshoot_runtime.time.time',lambda:self.now)
        self.clock.start();self.addCleanup(self.clock.stop)
        self.runtime=StationTroubleshootRuntime({})
        self.view={'blocked':[],'listeners_present':1,'page_speech_active':False,'speech_quiet_seconds':90}
        self.runtime.observe=AsyncMock(side_effect=lambda:dict(self.view))
        self.runtime.maintain=AsyncMock(return_value=False)
        self.manager=SimpleNamespace(status=Mock(return_value={'running':False}),
                                     start=Mock(return_value={'id':'automatic-job'}))
        self.runtime.get_manager=AsyncMock(return_value=self.manager)

    async def test_silence_starts_recovery_once_with_cooldown_and_retries_pending(self):
        self.assertTrue(await self.runtime.watch_once())
        self.assertFalse(await self.runtime.watch_once())
        self.now+=240
        self.assertTrue(await self.runtime.watch_once())
        self.assertEqual(self.manager.start.call_count,2)
        self.manager.start.assert_called_with(allow_restarts=True)

    async def test_manual_running_job_is_reused(self):
        self.manager.status.return_value={'running':True}
        self.assertFalse(await self.runtime.watch_once())
        self.manager.start.assert_not_called()

    async def test_pause_no_listener_active_speech_and_short_gaps_do_not_start(self):
        for field,value in [('blocked',['paused']),('listeners_present',0),
                            ('page_speech_active',True),('speech_quiet_seconds',59)]:
            old=self.view[field];self.view[field]=value
            self.assertFalse(await self.runtime.watch_once())
            self.view[field]=old
        self.manager.start.assert_not_called()

    async def test_transport_repair_is_not_blocked_by_busy_writer_or_recording(self):
        self.view.update(cure='',ready=2,banter_ready=2,writer_busy=True,recording_busy=True,
            unstarted_oldest_seconds=120,delivery_waiting=0,render_waiting=0,synth_tried=0,
            synth_done=0,uptime=100,workers_present=1,cause='healthy',why='',incomplete_recordings=0)
        self.runtime.ns={'dialogue_quiet_for':lambda:100}
        diagnosis=await self.runtime.diagnose()
        self.assertEqual(diagnosis['actions'][0]['step'],'delivery_reset')
        self.assertEqual(diagnosis['cause'],'unheard_dialogue_reservations')

    async def test_player_reload_is_escalated_only_after_unconfirmed_reset_window(self):
        self.view.update(cure='reload_pages',ready=2,banter_ready=2,writer_busy=True,recording_busy=True,
            unstarted_oldest_seconds=120,delivery_waiting=0,render_waiting=0,synth_tried=0,
            synth_done=0,uptime=100,workers_present=1,cause='healthy',why='',heard_at=700,
            delivery_recovery={'republished':2,'at':950},incomplete_recordings=0)
        self.runtime.ns={'dialogue_quiet_for':lambda:100}
        first=await self.runtime.diagnose()
        self.assertEqual([a['step'] for a in first['actions']],['delivery_reset'])
        self.now+=41
        second=await self.runtime.diagnose()
        self.assertEqual([a['step'] for a in second['actions']],['delivery_reset','reload_pages'])


if __name__=='__main__':unittest.main()
