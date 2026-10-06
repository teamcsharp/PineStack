import threading
import unittest
from station_flow_guard import ShelfSnapshots, recovery_yield, segment_budget
import dialogue_recovery as recovery


class FlowTests(unittest.TestCase):
    def test_slow_shelf_does_not_block_readers_or_duplicate_refresh(self):
        enter, release = threading.Event(), threading.Event()
        calls=[]
        def load():
            calls.append(1);enter.set();release.wait(2);return ["new"]
        cache=ShelfSnapshots(workers=1)
        try:
            self.assertEqual(cache.get("one",load,default=["old"]),["old"])
            self.assertTrue(enter.wait(1))
            for _ in range(20):self.assertEqual(cache.get("one",load,default=[]),["old"])
            self.assertEqual(len(calls),1)
            release.set()
            cache.close()
            self.assertEqual(cache.get("one",load),["new"])
        finally:release.set();cache.close()

    def test_failed_refresh_keeps_last_complete_snapshot(self):
        cache=ShelfSnapshots(workers=1)
        def failed():raise OSError("share offline")
        try:
            self.assertEqual(cache.get("one",failed,default=["kept"]),["kept"])
            cache.close()
            self.assertEqual(cache.get("one",failed),["kept"])
        finally:cache.close()

    def test_fresh_writing_has_priority_only_while_reserve_is_thin(self):
        job={"category":"station","state":"waiting"}
        self.assertTrue(recovery_yield(0,False,[job]))
        self.assertTrue(recovery_yield(60,True,[]))
        self.assertFalse(recovery_yield(120,True,[job]))
        self.assertFalse(recovery_yield(0,False,[]))

    def test_ad_reserve_cannot_displace_fresh_conversation_when_banter_is_empty(self):
        job={"category":"station","state":"waiting"}
        self.assertTrue(recovery_yield(184,False,[job],banter_ready=False))
        self.assertFalse(recovery_yield(184,False,[job],banter_ready=True))
        self.assertFalse(recovery_yield(184,False,[],banter_ready=False))

    def test_new_segment_size_never_cuts_calls_or_whole_passages(self):
        self.assertEqual(segment_budget(30),6)
        self.assertEqual(segment_budget(4),4)
        self.assertEqual(segment_budget(30,caller=True),30)
        self.assertEqual(segment_budget(30,whole=True),30)

    def test_missing_exact_source_is_parked_until_source_evidence_changes(self):
        row={"script":"original"};state=recovery.recovery_state(row)
        recovery.begin_attempt(state,100)
        recovery.note_failure(state,"a protected turn has no identified exact wording",101)
        self.assertFalse(recovery.begin_attempt(state,1000)["allow"])
        self.assertIsNone(recovery.pick_recovery_candidate([{"dialogue_recovery":state}],False,1000))
        self.assertTrue(recovery.needs_source(recovery.recovery_state(row)))
        row["script"]="corrected source wording"
        state=recovery.recovery_state(row)
        self.assertFalse(recovery.needs_source(state))
        self.assertTrue(recovery.begin_attempt(state,1001)["allow"])

    def test_repeated_same_rejection_backs_off_without_lifetime_abandonment(self):
        state=recovery.recovery_state({})
        for i in range(9):
            now=i*1000
            self.assertTrue(recovery.begin_attempt(state,now)["allow"])
            recovery.note_failure(state,"alignment failed",now+1)
        self.assertGreaterEqual(state["cooldown_until"],8301)
        self.assertFalse(recovery.begin_attempt(state,8200)["allow"])
        self.assertTrue(recovery.begin_attempt(state,9000)["allow"])
