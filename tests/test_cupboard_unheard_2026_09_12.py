"""#1260: the cupboard was full of finished radio nobody was taking.

Measured 2026-09-12: 25 recorded memos from upstairs and 30 recorded
gallery rounds had never been on the air, the oldest 103 hours old, while
the same two roads were written and rendered LIVE ninety times in the
same 24 hours. Both doors from the cupboard to the air were shut for
ordinary running - a slot that almost never comes round, and a silence
the SFX Guy fills first - so nothing ever asked.

These tests pin the three things that would fail silently and still look
correct on a panel:

  * that the explanation the desk shows is the AIR'S OWN reason, not a
    second opinion about it. A row that is ready and unheard must say so
    in those words, and a row that is off brief must not;
  * that the standing consumer actually picks the LONGEST-waiting row
    rather than the head of a shelf, and refuses to run when the dial is
    off or the interval has not elapsed;
  * that the replace sweep never reaches for a row the air could still
    take. #1075 is the rule it would break: unheard radio is an argument
    for airing it, not for binning it.
"""
import asyncio
import time
import unittest
from unittest import mock

import app


def row(kind="manager", *, age_h=50.0, aired=0, ready=True, off_brief=False,
        seconds=40.0, made=2, chunks=2):
    at = time.time() - age_h * 3600.0
    entry = {"script": "A: a memo landed\nB: it did", "script_plain": "x",
             "script_tinted": "A: a memo landed\nB: it did", "use": "tinted",
             "chunks": chunks, "made": made, "keys": ["k1", "k2"],
             "prep_kind": kind, "off_brief": off_brief}
    return {"entry": entry, "at": at, "kind": kind, "seconds": seconds,
            "aired": aired, "aired_at": (at + 60.0) if aired else 0.0,
            "off_brief": off_brief, "cast": "cohost=a|dj=b",
            "sid": "%s-%s" % (kind, int(at)), "brief": {"want": "a memo"}}


class CupboardWhy(unittest.TestCase):
    """The desk says what the air decided, in the air's own words."""

    def setUp(self):
        self.patches = [
            mock.patch.object(app, "cast_signature", lambda: "cohost=a|dj=b"),
            mock.patch.object(app, "_larder_current", lambda e: True),
            mock.patch.object(app, "dialogue_tint_ready", lambda k, r: True),
            mock.patch.object(app, "_ready_slot_window",
                              lambda k: {"kind": "record", "deadline": 0.0}),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_ready_and_unheard_says_nobody_asked(self):
        """The finding itself. Nothing is wrong with the round; the reason
        it has not aired is that no road ever asked for it, and that has
        to be SAID rather than left as an absence of reasons."""
        r = row(age_h=103.0)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [r]):
            got = app.cupboard_why_row("manager", r)
        self.assertFalse(got["blocked"])
        self.assertTrue(got["never_heard"])
        codes = [x["code"] for x in got["reasons"]]
        self.assertIn("never_asked_for", codes)
        # ...and it must name the shut door, because that is the cure.
        self.assertIn("no_slot", codes)
        self.assertIn("4d", got["say"] + str(got["waited"]) or "")

    def test_off_brief_is_blocked_and_never_says_nobody_asked(self):
        """A row the air will never take must not be described as merely
        unlucky. Both halves matter: the operator decides what to remove
        from this text."""
        r = row(off_brief=True)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [r]):
            got = app.cupboard_why_row("manager", r)
        self.assertTrue(got["blocked"])
        codes = [x["code"] for x in got["reasons"]]
        self.assertIn("off_brief", codes)
        self.assertNotIn("never_asked_for", codes)

    def test_unrendered_and_clip_gone_are_told_apart(self):
        """"Written but never recorded" and "its recording was pruned"
        take opposite cures, and the desk showed neither."""
        half = row(made=1, chunks=2)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: False), \
                mock.patch.object(app, "shelf_rows", lambda k: [half]):
            got = app.cupboard_why_row("manager", half)
        self.assertIn("unrendered", [x["code"] for x in got["reasons"]])
        done = row(made=2, chunks=2)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: False), \
                mock.patch.object(app, "shelf_rows", lambda k: [done]):
            got = app.cupboard_why_row("manager", done)
        self.assertIn("clip_gone", [x["code"] for x in got["reasons"]])

    def test_queue_position_is_named(self):
        """FIFO is the whole reason a good row waits, and it was invisible."""
        first, second = row(age_h=80.0), row(age_h=70.0)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [first, second]):
            got = app.cupboard_why_row("manager", second)
        self.assertEqual(got["queue_ahead"], 1)
        self.assertIn("behind_others", [x["code"] for x in got["reasons"]])


class UnheardPick(unittest.TestCase):
    """The consumer spends the longest wait first, across roads."""

    def test_oldest_across_roads_wins(self):
        old_gallery = row("gallery", age_h=90.0)
        newer_manager = row("manager", age_h=10.0)
        shelves = {"manager": [newer_manager], "gallery": [old_gallery],
                   "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            kind, got, age = app.unheard_pick()
        self.assertEqual(kind, "gallery")
        self.assertIs(got, old_gallery)
        self.assertGreater(age, 80 * 3600)

    def test_spoken_round_precedes_older_station_id(self):
        old_id = row("station_id", age_h=90.0)
        spoken = row("manager", age_h=10.0)
        shelves = {"station_id": [old_id], "manager": [spoken]}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", return_value=True), \
                mock.patch.object(app, "cupboard_unheard_after", return_value=7200.0):
            kind, got, _ = app.unheard_pick()
        self.assertEqual(kind, "manager")
        self.assertIs(got, spoken)

    def test_recently_refused_row_does_not_block_next_spoken_round(self):
        first = row("manager", age_h=90.0)
        second = row("gallery", age_h=10.0)
        shelves = {"manager": [first], "gallery": [second]}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", return_value=True), \
                mock.patch.object(app, "cupboard_unheard_after", return_value=7200.0), \
                mock.patch.dict(app._UNHEARD_REFUSED, {id(first): time.time() + 300}, clear=True):
            kind, got, _ = app.unheard_pick()
        self.assertEqual(kind, "gallery")
        self.assertIs(got, second)

    def test_nothing_younger_than_the_dial_is_taken(self):
        shelves = {"manager": [row("manager", age_h=0.5)], "gallery": [],
                   "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            kind, got, _ = app.unheard_pick()
        self.assertIsNone(got)

    def test_a_row_that_has_been_out_is_never_picked(self):
        """This road exists for rounds NOBODY has heard. Repeats have
        their own rest and their own innings and must not borrow this."""
        shelves = {"manager": [row("manager", age_h=90.0, aired=1)],
                   "gallery": [], "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            _, got, _ = app.unheard_pick()
        self.assertIsNone(got)


class ProducedAdDispatch(unittest.IsolatedAsyncioTestCase):
    """A mixed spot is one file, not a dialogue round with takes."""

    async def test_exact_row_commits_only_after_transport_accepts_it(self):
        shelf = {"sid": "spot-shelf-1", "produced": "spot-1",
                 "at": time.time() - 7200}
        pile = [shelf]
        entry = {"id": "spot-1", "audio": "spot-1.mp3",
                 "text": "The finished commercial", "uses": 2}
        took = []
        handed = []

        async def carried(got, on_handoff=None):
            self.assertEqual(got["id"], "spot-1")
            self.assertTrue(callable(on_handoff))
            on_handoff()
            return True

        app._READY_SHELF_BUSY.clear()
        with mock.patch.dict(app._SHELF, {"ad": pile}, clear=False), \
                mock.patch.object(app, "_unheard_produced_ad_entry",
                                  return_value=entry), \
                mock.patch.object(app, "_floor_take",
                                  new=mock.AsyncMock(return_value=True)), \
                mock.patch.object(app, "_floor_drop") as floor_drop, \
                mock.patch.object(app, "_air_produced_ad", side_effect=carried), \
                mock.patch.object(app, "stock_used_by", return_value="hour-22"), \
                mock.patch.object(app, "alt_took",
                                  side_effect=lambda kind, row: took.append((kind, row))), \
                mock.patch.object(app, "_pantry_save"), \
                mock.patch.object(app, "ad_update") as update:
            got = await app._unheard_produced_ad_air(
                shelf, on_handoff=lambda: handed.append("accepted"))

        self.assertEqual(got, ["The finished commercial"])
        self.assertEqual(pile, [])
        self.assertEqual(shelf["used_by"], "hour-22")
        self.assertTrue(shelf.get("taken_at"))
        self.assertEqual(took, [("ad", shelf)])
        self.assertEqual(handed, ["accepted"])
        update.assert_called_once_with("spot-1", uses=3)
        floor_drop.assert_called_once_with(True)
        self.assertNotIn(id(shelf), app._READY_SHELF_BUSY)

    async def test_refused_transport_leaves_the_exact_row_on_the_shelf(self):
        shelf = {"sid": "spot-shelf-2", "produced": "spot-2",
                 "at": time.time() - 7200}
        pile = [shelf]
        entry = {"id": "spot-2", "audio": "spot-2.mp3",
                 "text": "Do not lose me", "uses": 0}
        app._READY_SHELF_BUSY.clear()
        with mock.patch.dict(app._SHELF, {"ad": pile}, clear=False), \
                mock.patch.object(app, "_unheard_produced_ad_entry",
                                  return_value=entry), \
                mock.patch.object(app, "_floor_take",
                                  new=mock.AsyncMock(return_value=True)), \
                mock.patch.object(app, "_floor_drop"), \
                mock.patch.object(app, "_air_produced_ad",
                                  new=mock.AsyncMock(return_value=False)), \
                mock.patch.object(app, "_pantry_save") as save, \
                mock.patch.object(app, "ad_update") as update:
            got = await app._unheard_produced_ad_air(shelf)

        self.assertEqual(got, [])
        self.assertEqual(pile, [shelf])
        save.assert_not_called()
        update.assert_not_called()

    async def test_standing_consumer_uses_the_produced_transport(self):
        shelf = {"sid": "spot-shelf-3", "produced": "spot-3",
                 "at": time.time() - 7200}
        produced = mock.AsyncMock(return_value=["a commercial"])
        dialogue = mock.AsyncMock(return_value=["wrong door"])
        old_at, old_rescue = app._UNHEARD_AT[0], app._RESCUE_AT[0]
        old_speaking = app._SPEAKING[0]
        # Only 30 seconds have passed against the ordinary seven-minute dial.
        # No air-ready banter is what makes this walk due. A viable draft
        # waiting on its recording must not suppress the rescue cadence.
        app._UNHEARD_AT[0] = time.time() - 30.0
        app._SPEAKING[0] = 0
        try:
            with mock.patch.dict(app._RADIO, {"on": True}, clear=False), \
                    mock.patch.object(app, "cupboard_unheard_on", return_value=True), \
                    mock.patch.object(app, "cupboard_unheard_every", return_value=420.0), \
                    mock.patch.object(app, "larder_stock_count", return_value=1), \
                    mock.patch.object(app, "larder_ready_count", return_value=0), \
                    mock.patch.object(app, "talk_quiet_for", return_value=0.0), \
                    mock.patch.object(app, "dialogue_quiet_for", return_value=-1.0), \
                    mock.patch.object(app, "radio_paused", return_value=False), \
                    mock.patch.object(app, "_floor_busy", return_value=False), \
                    mock.patch.object(app, "unheard_replace_sweep"), \
                    mock.patch.object(app, "unheard_pick",
                                      return_value=("ad", shelf, 7200.0)), \
                    mock.patch.object(app, "_unheard_produced_ad_air",
                                      new=produced), \
                    mock.patch.object(app, "_ready_shelf_air", new=dialogue), \
                    mock.patch.object(app, "retire_id", return_value="spot-3"), \
                    mock.patch.object(app, "pipeline_log"), \
                    mock.patch.object(app, "_UNHEARD_LOG", []):
                got = await app.unheard_stock_air()
        finally:
            app._UNHEARD_AT[0] = old_at
            app._RESCUE_AT[0] = old_rescue
            app._SPEAKING[0] = old_speaking

        self.assertEqual(got, "ad")
        produced.assert_awaited_once()
        args, kwargs = produced.await_args
        self.assertEqual(args, (shelf,))
        self.assertFalse(kwargs["force"])
        self.assertTrue(callable(kwargs["on_handoff"]))
        dialogue.assert_not_awaited()

    async def test_watchdog_timeout_does_not_cancel_waiting_playout(self):
        handed = asyncio.Event()
        finished = asyncio.Event()

        async def slow_handoff():
            await asyncio.sleep(0.04)
            handed.set()
            finished.set()
            return ["broadcast"]

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(
                app._unheard_until_handoff(slow_handoff(), handed), 0.01)
        await asyncio.wait_for(finished.wait(), 1.0)

    async def test_silence_rescue_yields_to_gap_audio_before_long_handoff(self):
        async def pending(*, force=False):
            self.assertTrue(force)
            await asyncio.sleep(1)

        with mock.patch.object(app, "AIR1186_SILENCE_CUPBOARD_S", 0.01), \
                mock.patch.object(app, "unheard_stock_air", side_effect=pending), \
                mock.patch.object(app, "_dead_air_late") as late:
            self.assertEqual(await asyncio.wait_for(
                app._silence_cupboard_handoff(), 2.0), "")
            late.assert_called_once_with("the cupboard's silence rescue")

    async def test_silence_rescue_accepts_a_ready_cupboard_handoff(self):
        with mock.patch.object(app, "unheard_stock_air",
                               new=mock.AsyncMock(return_value="manager")), \
                mock.patch.object(app, "_dead_air_late") as late:
            self.assertEqual(await app._silence_cupboard_handoff(), "manager")
            late.assert_not_called()

    async def test_cancelled_watchdog_does_not_stack_another_cupboard_handoff(self):
        handed = asyncio.Event()
        release = asyncio.Event()

        async def slow_handoff():
            await release.wait()
            handed.set()
            return ["broadcast"]

        waiting = asyncio.create_task(
            app._unheard_until_handoff(slow_handoff(), handed))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertIn(handed, app._UNHEARD_PENDING_HANDOFFS)
        old_speaking = app._SPEAKING[0]
        app._SPEAKING[0] = 0
        try:
            with mock.patch.dict(app._RADIO, {"on": True}, clear=False), \
                    mock.patch.object(app, "cupboard_unheard_on", return_value=True), \
                    mock.patch.object(app, "radio_paused", return_value=False), \
                    mock.patch.object(app, "talk_quiet_for", return_value=100.0), \
                    mock.patch.object(app, "dialogue_quiet_for", return_value=-1.0), \
                    mock.patch.object(app, "_floor_busy", return_value=False), \
                    mock.patch.object(app, "unheard_pick") as pick:
                self.assertEqual(await app.unheard_stock_air(force=True), "")
                pick.assert_not_called()
        finally:
            app._SPEAKING[0] = old_speaking
            release.set()
            await asyncio.wait_for(handed.wait(), 1.0)
            await asyncio.sleep(0)
        self.assertNotIn(handed, app._UNHEARD_PENDING_HANDOFFS)

    async def test_stalled_handoff_defers_row_and_releases_single_flight(self):
        handed = asyncio.Event()
        row = {"sid": "stalled-stock"}

        async def never_handed():
            await asyncio.Event().wait()

        try:
            with mock.patch.object(app, "UNHEARD_HANDOFF_TIMEOUT", 0.02), \
                    mock.patch.object(app, "pipeline_log"):
                self.assertEqual(await asyncio.wait_for(
                    app._unheard_until_handoff(never_handed(), handed, row), 1.0), [])
            await asyncio.sleep(0)
            self.assertGreater(app._UNHEARD_REFUSED[id(row)], time.time())
            self.assertNotIn(handed, app._UNHEARD_PENDING_HANDOFFS)
        finally:
            app._UNHEARD_REFUSED.pop(id(row), None)

    async def test_transport_handoff_finishes_watchdog_before_playout_settles(self):
        """A long clip is accepted work at publication, while its tracked
        task keeps the floor until the clip's real airtime finishes."""
        shelf = row("manager", age_h=6.0)
        release = asyncio.Event()
        finished = asyncio.Event()

        async def long_playout(kind, track, *, rescue=False, pick=None,
                               force=False, on_handoff=None):
            self.assertIs(pick, shelf)
            self.assertTrue(callable(on_handoff))
            on_handoff()
            try:
                await release.wait()
                return ["one", "two"]
            finally:
                finished.set()

        old_at, old_rescue = app._UNHEARD_AT[0], app._RESCUE_AT[0]
        old_speaking = app._SPEAKING[0]
        old_sweep = dict(app._UNHEARD_SWEEP)
        app._UNHEARD_AT[0] = 0.0
        app._SPEAKING[0] = 0
        try:
            with mock.patch.dict(app._RADIO, {"on": True}, clear=False), \
                    mock.patch.object(app, "cupboard_unheard_on", return_value=True), \
                    mock.patch.object(app, "cupboard_unheard_every", return_value=420.0), \
                    mock.patch.object(app, "larder_ready_count", return_value=0), \
                    mock.patch.object(app, "talk_quiet_for", return_value=100.0), \
                    mock.patch.object(app, "dialogue_quiet_for", return_value=100.0), \
                    mock.patch.object(app, "radio_paused", return_value=False), \
                    mock.patch.object(app, "_floor_busy", return_value=False), \
                    mock.patch.object(app, "unheard_replace_sweep"), \
                    mock.patch.object(app, "unheard_pick",
                                      return_value=("manager", shelf, 21600.0)), \
                    mock.patch.object(app, "_ready_shelf_air",
                                      side_effect=long_playout), \
                    mock.patch.object(app, "retire_id", return_value="manager-long"), \
                    mock.patch.object(app, "pipeline_log"), \
                    mock.patch.object(app, "_UNHEARD_LOG", []):
                before = int(app._UNHEARD_SWEEP.get("aired") or 0)
                got = await asyncio.wait_for(
                    app.unheard_stock_air(force=True), timeout=15.0)
                self.assertEqual(got, "manager")
                self.assertFalse(finished.is_set())
                self.assertEqual(app._UNHEARD_SWEEP["aired"], before + 1)
                self.assertEqual(len(app._UNHEARD_LOG), 1)
                self.assertEqual(app._UNHEARD_LOG[0]["lines"], 2)
                release.set()
                await asyncio.wait_for(finished.wait(), timeout=15.0)
                await asyncio.sleep(0)
                self.assertEqual(app._UNHEARD_SWEEP["aired"], before + 1)
                self.assertEqual(len(app._UNHEARD_LOG), 1)
        finally:
            release.set()
            app._UNHEARD_AT[0] = old_at
            app._RESCUE_AT[0] = old_rescue
            app._SPEAKING[0] = old_speaking
            app._UNHEARD_SWEEP.clear()
            app._UNHEARD_SWEEP.update(old_sweep)


class BanterBootstrap(unittest.TestCase):
    """The reserve gets a playable first round before it grows deep."""

    def test_empty_larder_banks_a_short_complete_round_first(self):
        with mock.patch.object(app, "larder_ready_count", return_value=0):
            got = app.banter_bank_plan(30, bank=True)
        self.assertTrue(got["bootstrap"])
        self.assertFalse(got["rich"])
        self.assertEqual(got["judge_lines"], app.BANTER_BOOTSTRAP_LINES)
        self.assertEqual(got["lines"], app.BANTER_BOOTSTRAP_LINES)

    def test_one_ready_round_still_banks_a_short_complete_round(self):
        with mock.patch.object(app, "larder_ready_count", return_value=1):
            got = app.banter_bank_plan(12, bank=True)
        self.assertTrue(got["bootstrap"])
        self.assertFalse(got["rich"])
        self.assertEqual(got["judge_lines"], app.BANTER_BOOTSTRAP_LINES)

    def test_two_ready_rounds_keep_the_rich_expansion(self):
        with mock.patch.object(app, "larder_ready_count", return_value=2):
            got = app.banter_bank_plan(12, bank=True)
        self.assertFalse(got["bootstrap"])
        self.assertTrue(got["rich"])
        self.assertEqual(got["judge_lines"], 12)
        self.assertEqual(got["lines"], 16)

    def test_assigned_calls_are_never_shortened_by_an_empty_larder(self):
        with mock.patch.object(app, "larder_ready_count", return_value=0):
            got = app.banter_bank_plan(11, bank=True, bootstrap_ok=False)
        self.assertFalse(got["bootstrap"])
        self.assertTrue(got["rich"])
        self.assertEqual(got["judge_lines"], 11)
        self.assertEqual(got["lines"], 15)

    def test_system2_uses_beats_without_exceeding_its_slot_budget(self):
        got = app.banter_bank_plan(6, bank=True, system2_job=True,
                                   bootstrap_ok=False)
        self.assertFalse(got["bootstrap"])
        self.assertTrue(got["rich"])
        self.assertEqual(got["judge_lines"], 6)
        self.assertEqual(got["lines"], 6)


class FlatSingleTake(unittest.TestCase):
    """The original one-key shelf shape is a complete performance too."""

    def test_ready_validator_adapts_a_flat_pantry_take_without_rerendering(self):
        key = "flat-take-key"
        text = "The finished dry ad already has a voice and a measured clip."
        clip = {"path": "/voice-media/flat-take.wav", "seconds": 7.5}
        saved = {"clip": clip, "text": text, "voice": "xtts:host",
                 "who": "dj"}
        shelf = {"sid": "ad-flat", "key": key, "text": text,
                 "text_plain": text, "voice": "xtts:new-host",
                 "seconds": 7.5, "tint_ok": True}
        with mock.patch.dict(app._PANTRY, {key: saved}, clear=False), \
                mock.patch.object(app, "dialogue_row_ready", return_value=True), \
                mock.patch.object(app, "media_present", return_value=True):
            takes = app._ready_round_takes("ad", shelf)
            entry = app._ready_air_entry("ad", shelf)

        self.assertEqual(len(takes), 1)
        self.assertEqual(takes[0]["key"], key)
        # The recording's actual voice wins over a later cast setting.
        self.assertEqual(takes[0]["voice"], "xtts:host")
        self.assertEqual(takes[0]["clip"], clip)
        self.assertEqual(entry["script"], "A: " + text)
        self.assertEqual(entry["lines"], 1)
        self.assertTrue(entry["whole"])
        self.assertTrue(entry["render_stream"])
        self.assertEqual(entry["prep_kind"], "ad")

    def test_station_id_drop_seat_is_a_valid_saved_performance(self):
        key = "station-id-take"
        text = "Pine Box FM."
        clip = {"path": "/voice-media/station-id.wav", "seconds": 4.5}
        saved = {"clip": clip, "text": text, "voice": "xtts:drop", "who": "drop"}
        shelf = {"sid": "station-id-flat", "key": key, "text": text,
                 "seconds": 4.5, "tint_ok": True}
        with mock.patch.dict(app._PANTRY, {key: saved}, clear=False), \
                mock.patch.object(app, "dialogue_row_ready", return_value=True), \
                mock.patch.object(app, "media_present", return_value=True):
            takes = app._ready_round_takes("station_id", shelf)
            other = app._ready_round_takes("ad", shelf)
        self.assertEqual(len(takes), 1)
        self.assertEqual(takes[0]["who"], "drop")
        self.assertEqual(other, [])


class ReplaceSweep(unittest.TestCase):
    """"Replace what is not used" may never mean "bin unheard radio"."""

    def test_an_airable_unheard_row_is_never_offered_to_the_desk(self):
        old = row("manager", age_h=200.0)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [old]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(asked, [])

    def test_a_blocked_row_past_the_horizon_reaches_the_desk(self):
        dead = row("manager", age_h=200.0, off_brief=True)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [dead]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: False), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(len(asked), 1)
        self.assertIn("unheard", asked[0])

    def test_a_young_blocked_row_is_left_alone(self):
        dead = row("manager", age_h=2.0, off_brief=True)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [dead]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: False), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(asked, [])


class OutOfTurn(unittest.TestCase):
    """The sheet may not hold finished radio nobody has heard.

    Measured after the first deploy of this patch: the watchdog rung it
    shipped with never ran once in ten minutes, because /api/dj said
    box.floor was "a booth round" held for 248 seconds and the pair talk
    all but continuously. A cure that waits for a gap on this station is
    a cure that never runs, so the exemption has to apply where the ROAD
    asks - and only to rounds that have never been heard.
    """

    def test_an_overdue_unheard_row_is_free_of_the_sheet(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertTrue(app.unheard_free("manager", row(age_h=50.0)))

    def test_a_young_unheard_row_still_waits_its_turn(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=0.5)))

    def test_a_repeat_never_borrows_the_exemption(self):
        """A rested repeat has its own rest and its own innings. If this
        were true for aired rows the sheet would stop meaning anything."""
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=90.0, aired=2)))

    def test_the_switch_turns_it_off(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: False),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=90.0)))


class BothFitTestsAgree(unittest.TestCase):
    """The fit test is asked TWICE and both must ask the same question.

    _ready_shelf_air checks whether the round fits its slot once to
    select it and again after the floor has been taken, because the
    window can move while a round waits for the floor. The first #1260
    patch widened only the first: an unheard round was selected, the
    floor was taken for it, and the next line refused it with the
    sheet's answer. Measured live - a gallery entry aired 102 lines of
    banter under `round=gallery` with `kind=gallery` at zero, six
    minutes after that patch went live.

    A duplicated gate is not something a behavioural test can see from
    outside, so this reads the source. If the two ever disagree again
    this is the line that says so.
    """

    def test_no_fit_test_is_left_asking_rescue_alone(self):
        import inspect
        src = inspect.getsource(app._ready_shelf_air)
        self.assertIn("free = bool(rescue) or unheard_free(kind, row)", src)
        self.assertEqual(src.count("_ready_round_fits(kind, takes, window)"), 2,
                         "the number of fit tests changed - check both "
                         "honour `free`")
        self.assertNotIn("not rescue\n", src.replace(" ", ""))
        self.assertEqual(
            src.count("if not free and not _ready_round_fits"), 2,
            "both pre-floor and post-floor fit checks must use `free`")


class ConsumerCadenceReport(unittest.TestCase):
    """The panel and the consumer must publish the same emergency rest."""

    def test_empty_larder_cadence_is_visible_in_unheard_state(self):
        import inspect
        source = inspect.getsource(app.unheard_state)
        self.assertIn("larder_ready_count()", source)
        self.assertIn("UNHEARD_EMPTY_LARDER_EVERY", source)


if __name__ == "__main__":
    unittest.main()
