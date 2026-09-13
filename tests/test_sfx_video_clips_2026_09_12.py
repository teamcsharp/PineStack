"""#1263: THE CLIPS THE SFX GUY COULD SEE BUT NEVER REACH.

The operator: "ensure that the SFX guy is playing all media that he's
able to locate in the SFX directory. So if he's able to locate MP4s,
he's playing that in little pop up windows. If he's playing MP3s, he's
playing that as sound effects."

He was not. Every gate on the sample draw asked `suffix in MUSIC_TYPES`,
which is the MUSIC LIBRARY's table - audio only, because that is the
question it was written to answer. So a video clip in a sample folder
was never REFUSED anywhere; it was never a candidate, and no log, desk
or count anywhere said a word about it. Measured on the box the day this
went in: 2,656 .mp4 sitting in samples_grabbed/mwc, invisible.

These are the tests worth having because each one fails SILENTLY:

  * a type table that quietly excludes a format looks exactly like a
    library with nothing in it;
  * a levelling pass that decodes a video to wav serves a picture-less
    wav where the page asked for a picture, and the set comes on black;
  * a video drawn by the dead-air road answers silence with silence,
    because the panel is not where the operator is listening from;
  * a video welded into a round's concat graph takes the round with it;
  * and a video announced to the satellite is the soundtrack of
    something nobody can see.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class VideoIsASample(unittest.TestCase):
    """The type table, and the one question it now answers."""

    def test_the_draw_takes_pictures_and_the_music_index_does_not(self):
        # MUSIC_TYPES keeps answering only "is this a radio track" - the
        # 23,000-file pack tree must not turn into a playlist.
        self.assertNotIn(".mp4", app.MUSIC_TYPES)
        for suffix in (".mp4", ".webm", ".mov", ".mkv", ".m4v"):
            self.assertIn(suffix, app.SFX_TYPES, suffix)
            self.assertTrue(app.sfx_is_video(Path("a/b" + suffix)), suffix)
        for suffix in (".mp3", ".wav", ".flac"):
            self.assertIn(suffix, app.SFX_TYPES, suffix)
            self.assertFalse(app.sfx_is_video(Path("a/b" + suffix)), suffix)

    def test_a_name_that_is_not_a_path_is_not_a_crash(self):
        """sfx_is_video is asked about whatever the pool holds."""
        self.assertFalse(app.sfx_is_video(None))
        self.assertFalse(app.sfx_is_video(""))


class ThePoolSeesThem(unittest.TestCase):
    """The folder walk, which is where they were invisible."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for name in ("sting.mp3", "clip.mp4", "notes.txt", "art.png"):
            (self.folder / name).write_bytes(b"x" * 64)

    def test_sfx_list_takes_the_video_and_still_refuses_a_text_file(self):
        got = {p.name for p in app.sfx_list(self.folder)}
        self.assertEqual(got, {"sting.mp3", "clip.mp4"})

    def test_the_warm_road_takes_a_cached_video_duration(self):
        clip = self.folder / "clip.mp4"
        cache = {f"{clip}:{clip.stat().st_mtime_ns}": 2.0}
        with mock.patch.object(app, "_SFX_LEN_CACHE", cache):
            out = app._sfx_pool_warm([self.folder], 4.0, lambda: True,
                                     lambda rows: None)
        self.assertEqual(out, [clip])


class MeasuringAPicture(unittest.TestCase):
    """Length, and the two ways of asking for it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_zero_byte_download_is_never_handed_to_ffmpeg(self):
        """The drop share is full of them - 2,779 in one folder here -
        and one subprocess each to be told so is a walk that never ends."""
        empty = self.root / "never-finished.mp4"
        empty.write_bytes(b"")
        with mock.patch.object(app.subprocess, "run",
                               side_effect=AssertionError("probed an empty file")):
            self.assertEqual(app._media_duration_probe(empty), 0.0)

    def test_a_real_container_is_read_from_ffmpegs_own_header(self):
        clip = self.root / "real.webm"
        clip.write_bytes(b"x" * 8192)
        answer = mock.Mock(stderr="  Duration: 00:01:02.50, start: 0.000000\n")
        with mock.patch.object(app.subprocess, "run", return_value=answer):
            self.assertAlmostEqual(app._media_duration_probe(clip), 62.5)

    def test_duration_not_available_is_zero_and_not_an_exception(self):
        clip = self.root / "broken.mkv"
        clip.write_bytes(b"x" * 8192)
        answer = mock.Mock(stderr="  Duration: N/A, bitrate: N/A\n")
        with mock.patch.object(app.subprocess, "run", return_value=answer):
            self.assertEqual(app._media_duration_probe(clip), 0.0)

    def test_sfx_seconds_falls_through_to_the_probe_only_for_a_picture(self):
        video, audio = self.root / "a.webm", self.root / "b.mp3"
        for one in (video, audio):
            one.write_bytes(b"x" * 8192)
        with (mock.patch.object(app, "_SFX_LEN_CACHE", {}),
              mock.patch.object(app, "_SFX_LEN_DIRTY", [0]),
              mock.patch.object(app, "_media_duration_probe",
                                return_value=3.0) as probe):
            self.assertEqual(app.sfx_seconds(video), 3.0)
            self.assertEqual(app.sfx_seconds(audio), 0.0)
        self.assertEqual(probe.call_count, 1)


class ASilentPictureStillPlays(unittest.TestCase):
    """#1199's sound gate, and the one thing it must not bin."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "seen.mp4"
        self.audio = self.root / "heard.mp3"
        for one in (self.video, self.audio):
            one.write_bytes(b"x" * 8192)

    def test_a_measured_silent_video_airs_and_a_silent_mp3_does_not(self):
        with (mock.patch.object(app, "sfx_seconds", return_value=2.0),
              mock.patch.object(app, "sfx_is_silent", return_value=True),
              mock.patch.object(app, "sfx_cap_seconds", return_value=600.0),
              mock.patch.object(app, "sfx_floor_seconds", return_value=0.45)):
            self.assertTrue(app.sfx_short(self.video))
            self.assertFalse(app.sfx_short(self.audio))

    def test_the_length_gates_still_apply_to_a_picture(self):
        """Exempt from the SOUND gate, not from the clock."""
        with (mock.patch.object(app, "sfx_seconds", return_value=0.07),
              mock.patch.object(app, "sfx_is_silent", return_value=False),
              mock.patch.object(app, "sfx_cap_seconds", return_value=600.0),
              mock.patch.object(app, "sfx_floor_seconds", return_value=0.45)):
            self.assertFalse(app.sfx_short(self.video))

    def test_the_desk_never_offers_a_video_for_being_quiet(self):
        """A silent video in the deletion list is the desk arguing for
        the removal of exactly the clips this feature exists for."""
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn("and not sfx_is_video(path)):", source)


class LevellingLeavesAPictureAlone(unittest.TestCase):
    """sfx_levelled DECODES TO WAV. Handing the page a wav where it asked
    for a picture is how you get a set with nothing in it."""

    def test_a_video_is_served_exactly_as_it_was_shot(self):
        clip = Path("/samples/grabbed/mwc/49 do. Gee,.mp4")
        with mock.patch.object(app, "_as_wav",
                               side_effect=AssertionError("decoded a video")):
            self.assertIs(app.sfx_levelled(clip), clip)


class TheRoadsThatMustStayAudible(unittest.TestCase):
    """Two places where a picture instead of a sting is a fault, not a
    feature - and neither of them would have said so."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "seen.mp4"
        self.audio = self.root / "heard.mp3"
        for one in (self.video, self.audio):
            one.write_bytes(b"x" * 64)

    def test_the_dead_air_road_never_draws_a_picture(self):
        """sfx_fill_gap goes through _sfx_any, and its whole job is that
        silence gets ANSWERED - on the box, in the car, wherever the hole
        is actually being heard. A popup on the panel answers none of it."""
        with (mock.patch.object(app, "sfx_all",
                                return_value=[self.video, self.audio]),
              mock.patch.object(app, "sfx_short", return_value=True),
              mock.patch.object(app, "sfx_bans", return_value=set()),
              mock.patch.object(app, "unrepeated",
                                side_effect=lambda rows, *a, **k: rows[0])):
            for _ in range(8):
                self.assertEqual(app._sfx_any(), self.audio)

    def test_the_cadence_never_welds_a_picture_into_a_round(self):
        """Cadence punctuation is concatenated INTO the round's own wav.
        There is no picture in a rendered round to see one in."""
        settings = {**app.DEFAULT_DJ, "sfx_drop_folders": [self.root.name]}
        with (mock.patch.object(app, "SFX_ROOT", self.root.parent),
              mock.patch.object(app, "SFX_LOCAL_ROOT", self.root.parent),
              mock.patch.object(app, "dj_settings", return_value=settings),
              mock.patch.object(app, "_SFX_POOL_CACHE",
                                [self.video, self.audio]),
              mock.patch.object(app, "sfx_bans", return_value=set()),
              mock.patch.object(app, "sfx_weights", return_value={}),
              mock.patch.object(app, "sfx_seconds", return_value=2.0),
              mock.patch.object(app, "sfx_cap_seconds", return_value=600.0),
              mock.patch.object(app, "_SFX_CADENCE_STATUS", {})):
            for _ in range(8):
                self.assertEqual(app._sfx_cadence_pick(), self.audio)


class TheStingWithAPicture(unittest.IsolatedAsyncioTestCase):
    """dj_sting is the one door a sample airs through on its own."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sample = Path(self.temp.name) / "Gee.mp4"
        self.sample.write_bytes(b"x" * 64)
        self.audio = Path(self.temp.name) / "Gee.mp3"
        self.audio.write_bytes(b"x" * 64)
        self.radio = {"chat": [], "voice_to": "box", "on": True}
        self.fed = []
        self.boxed = []
        self.staged = []
        settings = {**app.DEFAULT_DJ, "drop_voice": "", "station_name": "Pine"}
        patches = [
            mock.patch.object(app, "_RADIO", self.radio),
            mock.patch.object(app, "dj_settings", return_value=settings),
            mock.patch.object(app, "_STING_AT", [0.0]),
            mock.patch.object(app, "_SPEAKING", [0]),
            mock.patch.object(app, "_SPOKE_AT", [0.0]),
            mock.patch.object(app, "_SAT_SAW_TURN_AT", [0.0]),
            mock.patch.object(app, "_BOX_DOWN", {}),
            mock.patch.object(app, "_BOX_HOLD", []),
            mock.patch.object(app, "sfx_seconds", return_value=2.5),
            mock.patch.object(app, "sfx_history_add"),
            mock.patch.object(app, "sfx_note_play"),
            mock.patch.object(app, "note_activity"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "media_sign", return_value="sig"),
            mock.patch.object(app, "satellite_busy",
                              mock.AsyncMock(return_value=False)),
            mock.patch.object(app, "page_feed_append",
                              side_effect=lambda clip: self.fed.append(clip) or "d1"),
            mock.patch.object(app, "_play_on_box",
                              mock.AsyncMock(side_effect=lambda *a: self.boxed.append(a))),
            mock.patch.object(app, "_episode_stage",
                              side_effect=lambda *a, **k: self.staged.append(a)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    async def test_a_video_goes_to_the_page_even_while_the_box_is_talking(self):
        """The ordinary arrangement here is voice_to=box, and in it the
        page feed is not written at all. A picture has nowhere else to go."""
        got = await app.dj_sting(True, sample=self.sample)
        self.assertEqual(got, self.sample.name)
        self.assertEqual(self.boxed, [], "a picture was announced to the Nabu")
        self.assertEqual(len(self.fed), 1)
        self.assertTrue(self.fed[0]["video"])
        self.assertEqual(self.fed[0]["seconds"], 2.5)

    async def test_the_booth_row_says_it_had_a_picture_and_that_it_aired(self):
        await app.dj_sting(True, sample=self.sample)
        row = self.radio["chat"][-1]
        self.assertTrue(row["video"])
        self.assertEqual(row["aired"], "page")

    async def test_a_video_is_never_staged_into_the_episode(self):
        """The episode is one concat graph mapping ONE audio output: an
        input with no audio stream at all fails the whole build, and the
        night's recording is worth more than a sting off it."""
        await app.dj_sting(True, sample=self.sample)
        self.assertEqual(self.staged, [])

    async def test_an_mp3_still_goes_to_the_box_and_is_still_recorded(self):
        """The old road, unchanged - which is the half of this that is
        easy to break and impossible to notice from the panel."""
        await app.dj_sting(True, sample=self.audio)
        self.assertEqual(len(self.boxed), 1)
        self.assertEqual(len(self.staged), 1)
        self.assertEqual(self.fed, [])
        self.assertFalse(self.radio["chat"][-1]["video"])


class TheSetsOwnDoor(unittest.IsolatedAsyncioTestCase):
    """/api/dj/video. The panel does not poll the VOICE feed while the box
    is doing the talking (djVoicePoll returns on its first line), which is
    the ordinary arrangement here - so without this the one surface a
    picture can air on is the one surface never asking for it."""

    def setUp(self):
        self.radio = {"voice_clips": [], "voice_cut_ms": 0}
        patches = [
            mock.patch.object(app, "_RADIO", self.radio),
            mock.patch.object(app, "require_read_auth"),
            mock.patch.object(app, "radio_paused", return_value=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def clip(self, **over):
        now = int(app.time.time() * 1000)
        row = {"ts": now, "broadcast_ms": now + 1000, "video": True,
               "seconds": 3.0, "url": "/sfx/abc?t=sig", "sting": "Gee"}
        row.update(over)
        self.radio["voice_clips"].append(row)
        return row

    async def test_only_the_clips_with_a_picture_come_back(self):
        self.clip()
        self.clip(video=False, sting="scratch")
        got = await app.dj_video_api(since=0)
        self.assertEqual(len(got["clips"]), 1)
        self.assertEqual(got["clips"][0]["sting"], "Gee")

    async def test_a_clip_whose_moment_has_gone_is_not_offered(self):
        """The set coming on over whatever is airing NOW is worse than
        the clip being missed - the same rule the voice feed keeps."""
        now = int(app.time.time() * 1000)
        self.clip(ts=now - 60000, broadcast_ms=now - 60000, seconds=2.0)
        self.assertEqual((await app.dj_video_api(since=0))["clips"], [])

    async def test_the_since_marker_is_honoured_so_a_set_plays_once(self):
        row = self.clip()
        self.assertEqual((await app.dj_video_api(since=row["ts"]))["clips"], [])

    async def test_a_paused_station_shows_nothing(self):
        self.clip()
        with mock.patch.object(app, "radio_paused", return_value=True):
            got = await app.dj_video_api(since=0)
        self.assertEqual(got["clips"], [])
        self.assertTrue(got["paused"])

    async def test_the_feed_epoch_cuts_a_dead_processs_clips(self):
        row = self.clip()
        self.radio["voice_cut_ms"] = row["ts"] + 1
        self.assertEqual((await app.dj_video_api(since=0))["clips"], [])


class ThePageContract(unittest.TestCase):
    """The set is built in CONTROL_PANEL_HTML, where nothing can import it.
    These read the source, because each one is a silent failure: a video
    handed to an <audio> element is a retry storm and a hole in the hour,
    and a tube animated on the FRAME would fight the operator's drag."""

    @classmethod
    def setUpClass(cls):
        cls.source = Path(app.__file__).read_text(encoding="utf-8")

    def test_a_picture_never_joins_the_speech_queue(self):
        self.assertIn("if (clip.video) { djVideoTv(clip); return; }", self.source)

    def test_the_tune_page_refuses_a_picture_rather_than_choking_on_it(self):
        self.assertIn("if (clip.video) return;", self.source)

    def test_the_set_comes_on_and_goes_off_like_a_tube(self):
        for frame in ("@keyframes sfxTvOn", "@keyframes sfxTvOff"):
            self.assertIn(frame, self.source, frame)
        # The close must reach a LINE and then a dot - "closes into a line
        # and disappears" - so the vertical scale collapses before the
        # horizontal one does.
        off = self.source.split("@keyframes sfxTvOff")[1][:420]
        self.assertIn("scale(1, .014)", off)     # the picture becomes a line
        self.assertIn("scale(.004, .004)", off)  # the line becomes a dot

    def test_the_tube_is_animated_and_not_the_frame(self):
        """pine-win remembers geometry from the box's own offsets. Animate
        the box and every frame of the animation is written to the
        operator's saved position."""
        self.assertIn(".sfx-tv-tube.on", self.source)
        self.assertIn(".sfx-tv-tube.off", self.source)
        self.assertNotIn("#pineWin-sfxTv.on", self.source)

    def test_the_picture_obeys_the_booth_monitor_and_the_solo_gate(self):
        self.assertIn('video.dataset.pineLive = "voice";', self.source)

    def test_the_set_has_a_watchdog(self):
        """onerror does not fire for every way a clip can fail to begin,
        and a set left on with a black tube holds the queue behind it."""
        self.assertIn('"the clip never started"', self.source)

    def test_inside_the_app_this_page_yields_to_the_shell(self):
        """The operator wants the set over EVERY view, which only the
        desktop shell can do - this page is one tab of that window. Two
        sets would be two pictures and two soundtracks, and the way that
        fails is by looking like a working feature twice over."""
        self.assertIn("if (pineInsideDesktopShell()) return;", self.source)
        self.assertIn('typeof window.pineDesktop.clipboardReady === "function"',
                      self.source)


if __name__ == "__main__":
    unittest.main()
