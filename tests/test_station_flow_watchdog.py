import copy
import unittest
from station_flow_watchdog import decide


class HostWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.args=dict(now=10000,wanted=True,paused=False,container={"Running":True,"started_at":9000},
                       health_ok=True,feed_ok=True,diagnosis={})

    def run_policy(self, state=None, **kw):
        return decide(state or {},**{**self.args,**kw})

    def test_transient_server_failure_does_not_restart(self):
        s=self.run_policy(health_ok=False,feed_ok=False)
        self.assertEqual(s["action"],"troubleshoot")
        self.assertEqual(s["health_failures"],1)
        s=self.run_policy(s)
        self.assertEqual(s["action"],"observe")
        self.assertEqual(s["health_failures"],0)

    def test_three_failed_probes_restart_only_wanted_running_station(self):
        s={}
        for n in range(3):s=self.run_policy(s,now=10000+30*n,health_ok=False,feed_ok=False)
        self.assertEqual(s["action"],"restart_station")
        for overrides in [{"wanted":False},{"paused":True},{"container":{"Running":False}},{"container":{"Running":True,"Paused":True}},
                          {"container":{"Running":True,"Restarting":True}}]:
            with self.subTest(overrides=overrides):
                self.assertEqual(self.run_policy(s,health_ok=False,**overrides)["action"],"hold")

    def test_startup_gets_grace_and_resets_old_failed_probe_counts(self):
        s=self.run_policy({"health_failures":9},health_ok=False,container={"Running":True,"started_at":9900})
        self.assertEqual(s["action"],"warming")
        self.assertEqual(s["health_failures"],0)

    def test_voice_feed_failure_with_confirmed_silence_escalates(self):
        s=self.run_policy({"feed_failures":2},feed_ok=False,
                          diagnosis={"listeners_present":1,"speech_quiet_seconds":200})
        self.assertEqual(s["action"],"restart_station")

    def test_advancing_audio_prevents_feed_or_health_failure_restart(self):
        s=self.run_policy({"feed_failures":9,"health_failures":9},feed_ok=False,health_ok=False,
                          diagnosis={"listeners_present":1,"speech_quiet_seconds":1,"page_speech_active":True})
        self.assertNotEqual(s["action"],"restart_station")

    def test_empty_house_or_short_speech_gap_never_escalates_a_voice_feed_failure(self):
        for diagnosis in [{"listeners_present":0,"speech_quiet_seconds":900},
                          {"listeners_present":1,"speech_quiet_seconds":20}]:
            self.assertNotEqual(self.run_policy({"feed_failures":8},feed_ok=False,diagnosis=diagnosis)["action"],"restart_station")

    def test_restart_cooldown_and_hourly_budget_survive_reload(self):
        s=self.run_policy({"health_failures":2,"last_restart_at":9950,"restart_times":[9950]},health_ok=False)
        self.assertEqual(s["action"],"cooldown")
        s=self.run_policy({"health_failures":2,"restart_times":[7000,8000,9000]},health_ok=False)
        self.assertEqual(s["action"],"attention")

    def test_recovery_requests_are_rate_limited(self):
        d={"listeners_present":1,"speech_quiet_seconds":100}
        self.assertEqual(self.run_policy(diagnosis=d)["action"],"troubleshoot")
        self.assertEqual(self.run_policy({"last_request_at":9950},diagnosis=d)["action"],"observe")

    def test_backlog_alone_does_not_spend_model_work_every_two_minutes(self):
        d={"production_health":{"state":"degraded","issues":["draft_recovery_pending"]}}
        self.assertEqual(self.run_policy(diagnosis=d)["action"],"observe")

    def test_stalled_reserve_maintenance_requests_owned_repair(self):
        d={"production_health":{"state":"degraded","issues":["conversation_reserve_low"]},"maintenance":{"at":9000}}
        self.assertEqual(self.run_policy(diagnosis=d)["action"],"troubleshoot")
        d["maintenance"]["at"]=9990
        self.assertEqual(self.run_policy(diagnosis=d)["action"],"observe")
        d["maintenance"]["at"]=9000;d["writer_busy"]=True
        self.assertEqual(self.run_policy(diagnosis=d)["action"],"observe")

    def test_policy_does_not_mutate_previous_durable_state(self):
        state={"restart_times":[1,9950]};before=copy.deepcopy(state)
        self.run_policy(state)
        self.assertEqual(state,before)


if __name__=="__main__":unittest.main()
