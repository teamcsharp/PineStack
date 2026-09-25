import asyncio
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import app
from parody_stinger_queue import ParodyQueue


def test_replay_stinger_keeps_operator_words_and_selected_source_window():
    async def exercise():
        with tempfile.TemporaryDirectory() as root:
            queue = ParodyQueue(Path(root) / "queue.sqlite3")
            reference = {"id": "0123456789abcdef", "name": "replayed-video",
                         "video": True, "seconds": 22.0}
            with (mock.patch.object(app, "_parody_stinger_queue", return_value=queue),
                  mock.patch.object(app, "_RADIO", {"on": False})):
                message, job = await app.voice_ad_render(
                    "jump up and down and point at the Pine Box sign", reference,
                    spoken_copy="Welcome to Pine Box FM.", trim_in_s=4.2,
                    trim_out_s=11.7)

            assert message == "Request completed."
            assert job["spoken_copy"] == "Welcome to Pine Box FM."
            assert job["trim_in_s"] == pytest.approx(4.2)
            assert job["trim_out_s"] == pytest.approx(11.7)
            with queue.connect() as db:
                row = db.execute("SELECT body FROM jobs WHERE id=?", (job["queue_id"],)).fetchone()
            body = json.loads(row["body"])
            assert body["speech"] == "Welcome to Pine Box FM."
            assert body["trim_in_s"] == pytest.approx(4.2)
            assert body["trim_out_s"] == pytest.approx(11.7)
            assert body["duration_seconds"] == pytest.approx(7.5)

    asyncio.run(exercise())


def test_replay_stinger_rejects_an_invalid_operator_source_window():
    async def exercise():
        reference = {"id": "0123456789abcdef", "name": "replayed-video",
                     "video": True, "seconds": 20.0}
        with pytest.raises(ValueError, match="between 2.2 and 15 seconds"):
            await app.voice_ad_render("wave", reference, trim_in_s=2, trim_out_s=3)

    asyncio.run(exercise())


def test_replay_stinger_desk_has_prompt_history_source_preview_and_shared_dictation():
    root = Path(__file__).resolve().parents[1]
    desk = (root / "desktop" / "renderer" / "hot-corners.js").read_text(encoding="utf-8")
    tablet = (root / "app" / "src" / "main" / "assets" / "pine-views" / "hot-corners.js").read_text(encoding="utf-8")
    desk_css = (root / "desktop" / "renderer" / "hot-corners.css").read_text(encoding="utf-8")
    tablet_css = (root / "app" / "src" / "main" / "assets" / "pine-views" / "hot-corners.css").read_text(encoding="utf-8")

    assert desk == tablet
    assert desk_css == tablet_css
    for expected in ("STINGER_HISTORY_STORE", "spoken_copy", "trim_in_s",
                     "trim_out_s", "hc-stinger-video", "PineTalkDot",
                     "Source video"):
        assert expected in desk
    assert "hc-stinger-source" in desk_css
