import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from system2_media import System2Media


def host(*, on=True, paused=True, ready=900.0, hours=4.0):
    return SimpleNamespace(
        _RADIO={"on": on},
        _HANDOFF_NO={},
        radio_paused=Mock(return_value=paused),
        schedule_horizon_hours=Mock(return_value=hours),
        prepare_target_seconds=Mock(return_value=hours * 3600.0),
        prepared_seconds=Mock(return_value=ready),
        dj_settings=Mock(return_value={"prepare_hours": hours}),
        _pantry_save=Mock(),
        _larder_save=Mock(),
        _banter_air=AsyncMock(side_effect=AssertionError("paused preparation aired")),
        page_feed_append=Mock(side_effect=AssertionError("paused preparation published")),
        _play_on_box=AsyncMock(side_effect=AssertionError("paused preparation played")),
    )


class OfflinePreparationContractTests(unittest.IsolatedAsyncioTestCase):
    def test_operator_pause_admits_preparation_but_never_air(self):
        adapter = System2Media(host(paused=True, hours=3.0))

        policy = adapter.preparation_contract(configured_horizon_hours=3)

        self.assertEqual(policy["mode"], "prepare_while_paused")
        self.assertTrue(policy["prepare_allowed"])
        self.assertFalse(policy["air_allowed"])
        self.assertEqual(policy["horizon_hours"], 4.0)
        self.assertEqual(policy["target_seconds"], 4 * 3600.0)
        self.assertEqual(policy["ready_seconds"], 900.0)
        self.assertEqual(policy["remaining_seconds"], 4 * 3600.0 - 900.0)
        self.assertTrue(policy["readiness_known"])

    def test_larger_configured_horizon_is_honored_and_bounded(self):
        adapter = System2Media(host(paused=True, ready=6 * 3600, hours=6.0))

        policy = adapter.preparation_contract(configured_horizon_hours=8)
        bounded = adapter.preparation_contract(configured_horizon_hours=1000)

        self.assertEqual(policy["horizon_hours"], 8.0)
        self.assertEqual(policy["remaining_seconds"], 2 * 3600.0)
        self.assertEqual(bounded["horizon_hours"], 24.0)

    def test_off_station_admits_neither_preparation_nor_air(self):
        adapter = System2Media(host(on=False, paused=True))

        policy = adapter.preparation_contract()

        self.assertEqual(policy["mode"], "off")
        self.assertFalse(policy["prepare_allowed"])
        self.assertFalse(policy["air_allowed"])

    def test_unknown_pause_state_is_prepare_only_and_air_fails_closed(self):
        fixture = host(paused=False)
        fixture.radio_paused.side_effect = RuntimeError("pause store unavailable")
        adapter = System2Media(fixture)

        policy = adapter.preparation_contract()

        self.assertTrue(policy["prepare_allowed"])
        self.assertFalse(policy["air_allowed"])
        self.assertFalse(policy["pause_known"])
        self.assertTrue(policy["operator_paused"])
        self.assertFalse(adapter.air_allowed())

    def test_paused_checkpoint_uses_only_existing_durable_stores(self):
        fixture = host(paused=True)
        adapter = System2Media(fixture)

        saved = adapter.checkpoint_preparation(pantry=True, larder=True)

        self.assertEqual(saved, ("pantry", "larder"))
        fixture._pantry_save.assert_called_once_with(True)
        fixture._larder_save.assert_called_once_with()
        fixture._banter_air.assert_not_awaited()
        fixture.page_feed_append.assert_not_called()
        fixture._play_on_box.assert_not_awaited()

    async def test_delivery_remains_closed_during_operator_pause(self):
        fixture = host(paused=True)
        adapter = System2Media(fixture)
        take = {"i": 0, "text": "prepared line", "voice": "dj", "who": "dj",
                "key": "saved", "audio_hash": "verified"}
        resolved = {"ready": True, "kind": "banter", "source_row": {},
                    "media_kind": "round", "entry": {"script": "A: prepared line"},
                    "takes": [take]}
        adapter._current = Mock(return_value=resolved)
        handoff = Mock()
        admission = Mock(return_value=True)

        self.assertFalse(await adapter.deliver(resolved, handoff, admission))

        self.assertEqual(adapter.last_refusal, "the station is off or paused")
        handoff.assert_not_called()
        admission.assert_not_called()
        fixture._banter_air.assert_not_awaited()
        fixture.page_feed_append.assert_not_called()
        fixture._play_on_box.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
