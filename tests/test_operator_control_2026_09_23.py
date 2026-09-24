"""Focused contracts for the new operator controls."""
import copy
import inspect
import unittest
from unittest import mock

import app
import caller_topic


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class EndlessBanking(unittest.TestCase):
    def test_endless_mode_owns_only_the_pause_it_created(self):
        settings = {"dj": {"sfx_video_mode": False,
                           "sfx_video_banking_owned": False}}
        paused = [False]
        calls = []

        def save(value):
            settings.clear()
            settings.update(copy.deepcopy(value))

        def pause(on, why=""):
            paused[0] = bool(on)
            calls.append((bool(on), why))

        with mock.patch.object(app, "load_settings",
                               side_effect=lambda: copy.deepcopy(settings)), \
                mock.patch.object(app, "save_settings", side_effect=save), \
                mock.patch.object(app, "dj_settings",
                                  side_effect=lambda: settings["dj"]), \
                mock.patch.object(app, "radio_paused",
                                  side_effect=lambda: paused[0]), \
                mock.patch.object(app, "radio_pause_set", side_effect=pause), \
                mock.patch.object(app, "_sfx_video_withdraw") as withdraw:
            app.sfx_video_banking_set(True, "test")
            self.assertTrue(settings["dj"]["sfx_video_mode"])
            self.assertTrue(settings["dj"]["sfx_video_banking_owned"])
            self.assertTrue(paused[0])
            app.sfx_video_banking_set(False, "test over")

        self.assertFalse(paused[0])
        self.assertEqual([c[0] for c in calls], [True, False])
        withdraw.assert_called_once()

    def test_preexisting_pause_is_not_released(self):
        settings = {"dj": {"sfx_video_mode": False,
                           "sfx_video_banking_owned": False}}
        with mock.patch.object(app, "load_settings",
                               side_effect=lambda: copy.deepcopy(settings)), \
                mock.patch.object(app, "save_settings",
                                  side_effect=lambda value: settings.update(copy.deepcopy(value))), \
                mock.patch.object(app, "dj_settings",
                                  side_effect=lambda: settings["dj"]), \
                mock.patch.object(app, "radio_paused", return_value=True), \
                mock.patch.object(app, "radio_pause_set") as pause, \
                mock.patch.object(app, "_sfx_video_withdraw"):
            app.sfx_video_banking_set(True)
            app.sfx_video_banking_set(False)
        pause.assert_not_called()


class RetirementQuestions(unittest.IsolatedAsyncioTestCase):
    def test_question_state_uses_actual_waiting_items(self):
        pending = {"pending": [{"id": "r1", "kind": "banter",
                                  "label": "Banter", "text": "one line",
                                  "why": "retention ended", "aired": 0}]}
        row = {"sid": "r1"}
        with mock.patch.object(app, "retire_state", return_value=pending), \
                mock.patch.object(app, "_retire_find", return_value=("banter", row)), \
                mock.patch.object(app, "cupboard_why_row",
                                  return_value={"reasons": [{"say": "ready and unheard"}]}), \
                mock.patch.object(app, "dialogue_row_ready", return_value=True):
            got = app.retire_question_state()
        self.assertEqual(got["items"][0]["id"], "r1")
        self.assertTrue(got["items"][0]["ready"])
        self.assertIn("air it", got["items"][0]["question"])


class TrackReader(unittest.IsolatedAsyncioTestCase):
    async def test_single_track_scan_uses_the_catalogue_reader(self):
        track = {"id": "abc", "title": "A Song", "artist": "An Artist",
                 "album": "An Album", "path": "/tmp/a.wav"}
        launched = []

        def fire(coro):
            launched.append(coro)
            coro.close()

        app._LYRIC_JOBS.clear()
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "music_track", return_value=track), \
                mock.patch.object(app, "mind_id", return_value="main"), \
                mock.patch.object(app, "fire_and_forget", side_effect=fire), \
                mock.patch.object(app, "_lyric_run", new=mock.AsyncMock()):
            got = await app.music_track_read(Request({"id": "abc"}), "Bearer test")
        self.assertEqual(got["tracks"], 1)
        self.assertEqual(got["track"], "A Song")
        self.assertEqual(len(launched), 1)


class PreparedRoundMetadata(unittest.IsolatedAsyncioTestCase):
    async def test_floor_wrapper_passes_fresh_scene_metadata_to_playout(self):
        metadata = {"prep_kind": "banter", "prompt": "the active brief"}
        floorless = mock.AsyncMock(return_value=["aired"])
        with mock.patch.object(app, "_speak_turns_floorless", floorless), \
                mock.patch.object(app, "_floor_take", new=mock.AsyncMock(return_value="floor")), \
                mock.patch.object(app, "_floor_drop"):
            got = await app.speak_turns([("A", "A complete line.")], None, 1,
                                        round_meta=metadata)
        self.assertEqual(got, ["aired"])
        self.assertEqual(floorless.await_args.kwargs["round_meta"], metadata)
        self.assertIn("round_meta", inspect.signature(app._speak_turns_floorless).parameters)


class DirectorPreparedDialogue(unittest.IsolatedAsyncioTestCase):
    def test_unbound_draft_keeps_its_turns_for_the_calendar(self):
        slot = {"drafts": [{
            "id": "draft-one",
            "script": "A: First prepared thought.\nB: A specific reply.",
        }]}
        with mock.patch.object(app, "_director_seat",
                               side_effect=lambda marker: {"A": "Host", "B": "Skip"}[marker]):
            got = app._director_script(slot)
        self.assertEqual(got["state"], "drafts waiting")
        self.assertEqual(got["draft_candidates"], ["draft-one"])
        self.assertEqual([row["who"] for row in got["draft_turns"]],
                         ["Host", "Skip"])
        self.assertEqual(got["draft_turns"][1]["text"], "A specific reply.")
        self.assertEqual(len(got["draft_variants"]), 1)
        self.assertEqual(got["draft_variants"][0]["id"], "draft-one")

    def test_general_topic_review_rejects_a_mid_scene_subject_swap(self):
        turns = [
            ("A", "A burglar used my toilet and left a terrible mark."),
            ("B", "That bathroom has become a crime scene."),
            ("A", "The broth business feeds a monstrous hunger."),
            ("B", "The soup economy benefits the very few."),
            ("A", "Keep boiling it for the shareholders."),
        ]
        got = caller_topic.dialogue_topic_adherence(
            turns, "A burglar used my toilet and left a terrible mark")
        self.assertTrue(got["checked"])
        self.assertFalse(got["ok"])
        self.assertLess(got["score"], 0.5)

    async def test_operator_can_select_a_draft_winner(self):
        with mock.patch.object(app, "script_choose",
                               return_value={"candidate": "draft-two"}) as choose, \
                mock.patch.object(app, "_director_refresh_after_choice") as refresh:
            got = await app.api_director_winner("hour-1:slot", {
                "kind": "banter", "candidate": "draft-two",
                "candidates": ["draft-one", "draft-two"]})
        self.assertTrue(got["ok"])
        choose.assert_called_once()
        refresh.assert_called_once()

    async def test_line_feedback_reaches_the_director_book(self):
        with mock.patch.object(app, "script_note_feedback",
                               return_value={"action": "off_topic"}) as note, \
                mock.patch.object(app, "director_add"), \
                mock.patch.object(app, "_director_refresh_after_choice"):
            got = await app.api_director_feedback("hour-1:slot", {
                "kind": "banter", "action": "off_topic",
                "line": "This changed subjects.", "index": 2})
        self.assertTrue(got["ok"])
        note.assert_called_once()

    async def test_lean_playout_read_omits_the_audit_history(self):
        full = {
            "schema_version": 1,
            "available": True,
            "mode": "linear",
            "linear": True,
            "verdict": "sounding",
            "sounding": {"line_id": "line-one"},
            "current": None,
            "next": {"line_id": "line-two"},
            "now": 10.0,
            "history": [{"large": "audit"}],
            "events": [{"large": "audit"}],
        }
        with mock.patch.object(app, "require_read_auth"), \
                mock.patch.object(app, "playout_state", return_value=full):
            got = await app.playout_api(1, True, None)
        self.assertEqual(got["sounding"]["line_id"], "line-one")
        self.assertNotIn("history", got)
        self.assertNotIn("events", got)

    def test_playout_position_resolves_the_exact_script_line(self):
        rows = [
            {"block": 42, "ord": 0, "id": "line-one", "name": "Host",
             "line_id": "line-one", "text": "First.", "at": 100.0},
            {"block": 42, "ord": 1, "id": "line-two", "name": "Skip",
             "line_id": "line-two", "text": "Second.", "at": 100.0},
        ]
        air = [
            {"id": "line-one", "name": "Host", "clip_media": "round.wav",
             "clip_from": 0.0, "clip_until": 2.5},
            {"id": "line-two", "name": "Skip", "clip_media": "round.wav",
             "clip_from": 2.5, "clip_until": 7.0},
        ]
        app._PLAYOUT_LINE_CUES.clear()
        with mock.patch.object(app, "script_ledger_rows", return_value=rows), \
                mock.patch.object(app, "airlog_rows", return_value=air):
            got = app._playout_with_exact_line({
                "sounding": {"block": 42, "file": "round.wav",
                             "position_s": 4.0}
            })
        sounding = got["sounding"]
        self.assertEqual(sounding["line_id"], "line-two")
        self.assertEqual(sounding["ord"], 1)
        self.assertEqual(sounding["speaker"], "Skip")
        self.assertEqual(sounding["line_position_s"], 1.5)


if __name__ == "__main__":
    unittest.main()
