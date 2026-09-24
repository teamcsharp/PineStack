import asyncio
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from fastapi.responses import FileResponse

import app


def request(body):
    return SimpleNamespace(json=mock.AsyncMock(return_value=body))


class LineActionAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_presenter_clip_required(self):
        with tempfile.TemporaryDirectory() as root:
            clip = Path(root) / "line.mp3"
            clip.write_bytes(b"sound")
            row = {"who": "host", "media": "line.mp3", "text": "Exact line"}
            with mock.patch.object(app, "_booth_row", return_value=row), \
                    mock.patch.object(app, "booth_clip_api", new_callable=mock.AsyncMock,
                                      return_value=FileResponse(
                                          clip, headers={"X-Pine-Exact": "1"})):
                found, path = await app._line_action_voice("line-1", "Bearer test")
                self.assertEqual(found, row)
                self.assertEqual(path, clip)
            with mock.patch.object(app, "_booth_row", return_value=row), \
                    mock.patch.object(app, "booth_clip_api", new_callable=mock.AsyncMock,
                                      return_value=FileResponse(
                                          clip, headers={"X-Pine-Exact": "0"})):
                with self.assertRaises(HTTPException) as error:
                    await app._line_action_voice("line-1", "Bearer test")
                self.assertEqual(error.exception.status_code, 409)

    async def test_dry_route_is_exact_voice_only_and_does_not_air(self):
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "_line_action_voice", new_callable=mock.AsyncMock,
                                  return_value=({}, Path("unused"))) as voice, \
                mock.patch.object(app, "_air_produced_ad", new_callable=mock.AsyncMock) as air:
            result = await app.line_action_dry_voice(
                request({"line_id": "row/one"}), authorization="Bearer test")
        self.assertEqual(result["route"], "/api/booth/clip?line=row%2Fone")
        self.assertTrue(result["exact"])
        self.assertTrue(result["voice_only"])
        self.assertFalse(result["auto_air"])
        voice.assert_awaited_once_with("row/one", "Bearer test")
        air.assert_not_awaited()

    async def test_make_ad_schedules_exact_source_without_music(self):
        with tempfile.TemporaryDirectory() as root:
            sfx = Path(root) / "sfx.wav"
            sfx.write_bytes(b"sound")
            row = {"who": "cohost", "text": "These exact spoken words.",
                   "voice": "cohost-voice", "media": "line.mp3"}
            with mock.patch.object(app, "require_auth"), \
                    mock.patch.object(app, "_line_action_voice", new_callable=mock.AsyncMock,
                                      return_value=(row, Path(root) / "voice.mp3")), \
                    mock.patch.object(app, "sfx_db_pick", return_value=sfx), \
                    mock.patch.object(app, "_line_sfx_ad_write",
                                      return_value="abcdef123456.mp3") as mix, \
                    mock.patch.object(app, "ad_save", return_value={"id": "ad-1", "product": row["text"]}) as save, \
                    mock.patch.object(app, "shelf_put") as shelve, \
                    mock.patch.object(app, "_air_produced_ad", new_callable=mock.AsyncMock) as air:
                result = await app.line_action_make_ad(
                    request({"line_id": "row-1", "sfx": "random", "music": False}),
                    authorization="Bearer test")
            self.assertEqual(result["ad_id"], "ad-1")
            self.assertFalse(result["music"])
            self.assertTrue(result["auto_air"])
            self.assertTrue(result["scheduled"])
            self.assertEqual(mix.call_args.args[0], Path(root) / "voice.mp3")
            self.assertEqual(mix.call_args.args[1], sfx)
            args = save.call_args.args
            self.assertEqual(args[1], row["text"])
            self.assertEqual(args[3]["source_line_id"], "row-1")
            self.assertEqual(args[3]["source_voice"], "cohost-voice")
            self.assertTrue(args[3]["source_exact"])
            self.assertEqual(args[3]["sfx_source"], str(sfx))
            self.assertFalse(args[3]["music"])
            self.assertTrue(args[3]["auto_air"])
            self.assertEqual(shelve.call_args.args[0], "ad")
            self.assertEqual(shelve.call_args.args[1]["produced"], "ad-1")
            self.assertEqual(shelve.call_args.args[1]["audio"], "abcdef123456.mp3")
            air.assert_not_awaited()

    async def test_make_ad_rejects_music_bed_request(self):
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "_line_action_voice", new_callable=mock.AsyncMock) as voice:
            with self.assertRaises(HTTPException) as error:
                await app.line_action_make_ad(
                    request({"line_id": "row-1", "sfx": "random", "music": True}),
                    authorization="Bearer test")
            self.assertEqual(error.exception.status_code, 400)
            voice.assert_not_awaited()

    def test_ffmpeg_mix_has_only_voice_and_sfx_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            voice, sfx = root / "voice.wav", root / "sfx.wav"
            for path in (voice, sfx):
                with wave.open(str(path), "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(44100)
                    out.writeframes(b"\x00\x00" * 44100)
            with mock.patch.object(app, "PRODUCED_ADS_DIR", root):
                name = app._line_sfx_ad_write(voice, sfx, "abcdef123456.mp3")
            self.assertEqual(name, "abcdef123456.mp3")
            self.assertGreater((root / name).stat().st_size, 1000)

    def test_manual_only_ad_is_not_picked_for_automatic_air(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "abcdef123456.mp3").write_bytes(b"sound")
            draft = {"id": "ad-1", "audio": "abcdef123456.mp3",
                     "uses": 0, "auto_air": False}
            with mock.patch.object(app, "ad_list", return_value=[draft]), \
                    mock.patch.object(app, "PRODUCED_ADS_DIR", root), \
                    mock.patch.object(app, "_SHELF", {"ad": []}):
                self.assertIsNone(app.ad_pick())
                self.assertIsNone(app.coord_spot_ready())


if __name__ == "__main__":
    unittest.main()
