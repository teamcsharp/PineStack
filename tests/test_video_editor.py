"""Real media edits in isolated directories; never import the station app."""
import base64
import io
import json
import time
import uuid
import sys
import threading

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from video_editor import (EXPORT_SHARE, VideoEditor, create_video_editor_router,
                          normalize_edit, export_command)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("video-editor")
    editor = VideoEditor(root / "data", root)
    original = root / "fixture.mp4"
    editor.run([editor.ffmpeg, "-v", "error", "-nostdin", "-y", "-threads", "1",
                "-f", "lavfi", "-i", "testsrc2=duration=4:size=160x96:rate=12",
                "-itsoffset", "1", "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-threads", "1",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "4", str(original)])
    yield editor, original
    editor.worker.shutdown(wait=True)


def wait_record(editor, kind, identifier):
    limit = time.monotonic() + 60
    while time.monotonic() < limit:
        record = editor.read(kind, identifier)
        if record["status"] in ("ready", "complete", "failed"):
            assert record["status"] != "failed", record
            return record
        time.sleep(.03)
    pytest.fail("Media worker did not finish")


def source(editor, original):
    identifier = uuid.uuid4().hex
    folder = editor.folder("sources", identifier)
    folder.mkdir(parents=True)
    (folder / "original.mp4").write_bytes(original.read_bytes())
    editor.write("sources", identifier, {"id": identifier, "status": "processing"})
    editor.submit("sources", identifier, lambda: editor.analyze(identifier))
    return wait_record(editor, "sources", identifier)


def test_analysis_reads_real_audio_and_time_offset(media):
    editor, original = media
    item = source(editor, original)
    assert (item["width"], item["height"]) == (160, 96)
    assert item["has_audio"] and item["audio_signal"] == "present"
    assert len(item["waveform"]) == 2048
    assert max(item["waveform"][:400]) < .001
    assert max(item["waveform"][600:]) > .05
    folder = editor.folder("sources", item["id"])
    assert Image.open(folder / "spectrum.png").size == (1024, 96)
    assert Image.open(folder / "thumbnails.jpg").size == (960, 192)


def test_pyav_probe_works_without_ffprobe(media):
    editor, original = media
    info = editor.probe_av(original)
    assert info["duration"] == pytest.approx(4, abs=.1)
    assert info["audio_start_s"] == pytest.approx(1, abs=.03)
    assert info["audio_sample_rate"] == 48000


def test_trim_preserves_audio_offset_and_original(media):
    editor, original = media
    item = source(editor, original)
    before = original.read_bytes()
    job = editor.start_export({"source_id": item["id"], "in_s": .5, "out_s": 3,
                               "include_audio": True})
    done = wait_record(editor, "exports", job["id"])
    assert job["id"] in done["name"]
    assert done["duration"] == pytest.approx(2.5, abs=.1)
    assert done["has_audio"]
    output = editor.folder("exports", job["id"]) / "edited.mp4"
    raw = editor.run([editor.ffmpeg, "-v", "error", "-i", str(output), "-map", "0:a:0",
                      "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1"])
    audio = np.frombuffer(raw, dtype="<f4")
    assert np.max(np.abs(audio[:2500])) < .005  # first 0.31 s remains quiet
    assert np.max(np.abs(audio[5000:8000])) > .05
    assert original.read_bytes() == before
    assert (editor.folder("sources", item["id"]) / "original.mp4").read_bytes() == before


def test_draw_crop_rotation_and_audio_removal_are_in_export(media):
    editor, original = media
    item = source(editor, original)
    ink = Image.new("RGBA", (160, 96), (0, 255, 0, 255))
    png = io.BytesIO()
    ink.save(png, format="PNG")
    job = editor.start_export({"source_id": item["id"], "in_s": 1, "out_s": 2,
                               "crop": {"x": 0, "y": 0, "w": .5, "h": .5}, "rotation": 90,
                               "brightness": .5, "include_audio": False,
                               "overlay_png": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()})
    done = wait_record(editor, "exports", job["id"])
    assert (done["width"], done["height"]) == (48, 80)
    assert not done["has_audio"]
    output = editor.folder("exports", job["id"]) / "edited.mp4"
    pixels = editor.run([editor.ffmpeg, "-v", "error", "-i", str(output), "-frames:v", "1",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    frame = np.frombuffer(pixels, dtype="uint8").reshape(80, 48, 3)
    assert frame[40, 24, 1] > 240  # correction is before the green annotation
    assert frame[40, 24, 0] < 10


def test_color_correction_changes_saved_pixels(media, tmp_path):
    editor, original = media
    info = editor.probe(original)
    values = []
    for brightness in (1, .5):
        edit = normalize_edit({"in_s": 0, "out_s": .5, "brightness": brightness,
                               "saturation": 0, "include_audio": False}, info)
        output = tmp_path / f"brightness-{brightness}.mp4"
        editor.run(export_command(original, output, edit, ffmpeg=editor.ffmpeg))
        raw = editor.run([editor.ffmpeg, "-v", "error", "-i", str(output), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
        pixels = np.frombuffer(raw, dtype="uint8").reshape(-1, 3).astype(float)
        assert np.mean(np.abs(pixels[:, 0] - pixels[:, 1])) < 3
        values.append(pixels.mean())
    assert values[1] == pytest.approx(values[0] / 2, abs=3)


@pytest.mark.parametrize("edit", [
    {"in_s": float("nan")}, {"out_s": 10}, {"in_s": 2, "out_s": 1},
    {"rotation": 45}, {"crop": {"x": .9, "y": 0, "w": .5, "h": 1}},
    {"crop": {"x": 0, "y": 0, "w": 0, "h": 1}}, {"include_audio": "false"},
    {"brightness": "1;movie=/etc/passwd"},
])
def test_invalid_edit_is_refused(edit):
    with pytest.raises(ValueError):
        normalize_edit(edit, {"duration": 4, "width": 160, "height": 96, "has_audio": True})


def test_absent_audio_cannot_be_claimed():
    with pytest.raises(ValueError, match="no captured audio"):
        normalize_edit({"include_audio": True}, {"duration": 4, "width": 160, "height": 96, "has_audio": False})


def test_interrupted_job_remains_explicit(tmp_path):
    editor = VideoEditor(tmp_path, tmp_path)
    identifier = uuid.uuid4().hex
    editor.write("exports", identifier, {"id": identifier, "status": "working"})
    assert editor.read("exports", identifier)["status"] == "failed"
    editor.worker.shutdown(wait=True)


def test_delivery_requires_matching_file_on_share(tmp_path):
    root = tmp_path / "data" / "video_edits"
    share = tmp_path / "share"
    share.mkdir()
    editor = VideoEditor(root, tmp_path, export_verify_dir=share)
    identifier = uuid.uuid4().hex
    name = f"Pine-{identifier}-edited.mp4"
    folder = editor.folder("exports", identifier)
    folder.mkdir(parents=True)
    (folder / "edited.mp4").write_bytes(b"real-edited-clip")
    editor.write("exports", identifier, {"id": identifier, "status": "complete",
                 "name": name, "created_at_ms": int(time.time() * 1000)})
    (root.parent / "settings.json").write_text(
        json.dumps({"export_desk_dir": EXPORT_SHARE}), encoding="utf-8")
    assert editor.delivery_status(identifier)["status"] == "not_requested"

    ledger = root.parent / "export_courier.json"
    row = {"id": "0123456789", "what": "video-edit", "name": name,
           "bytes": len(b"real-edited-clip"), "dest": EXPORT_SHARE,
           "at": time.time(), "state": "pending"}
    ledger.write_text(json.dumps([row]), encoding="utf-8")
    assert editor.delivery_status(identifier)["status"] == "pending"
    row.update(state="delivered", delivered=EXPORT_SHARE + "\\" + name)
    ledger.write_text(json.dumps([row]), encoding="utf-8")
    assert editor.delivery_status(identifier)["status"] == "verifying"
    (share / name).write_bytes(b"fake-edited-clip")
    assert editor.delivery_status(identifier)["status"] == "conflict"
    (share / name).write_bytes(b"real-edited-clip")
    delivered = editor.delivery_status(identifier)
    assert delivered["status"] == "delivered"
    assert delivered["verified"] == "sha256"
    assert delivered["path"] == EXPORT_SHARE + "\\" + name
    editor.close()


def test_delivery_preflight_rejects_wrong_destination(tmp_path):
    root = tmp_path / "data" / "video_edits"
    share = tmp_path / "share"
    share.mkdir()
    editor = VideoEditor(root, tmp_path, export_verify_dir=share)
    identifier = uuid.uuid4().hex
    folder = editor.folder("exports", identifier)
    folder.mkdir(parents=True)
    (folder / "edited.mp4").write_bytes(b"clip")
    editor.write("exports", identifier, {"id": identifier, "status": "complete",
                 "name": "edited.mp4"})
    (root.parent / "settings.json").write_text(
        json.dumps({"export_desk_dir": r"C:\Other"}), encoding="utf-8")
    assert editor.delivery_status(identifier)["status"] == "wrong_destination"
    editor.close()


def test_shutdown_terminates_running_media_process(tmp_path):
    editor = VideoEditor(tmp_path, tmp_path)
    failures = []

    def work():
        try:
            editor.run([sys.executable, "-c", "import time; time.sleep(10)"])
        except ValueError as exc:
            failures.append(str(exc))

    thread = threading.Thread(target=work)
    thread.start()
    for _ in range(200):
        if editor.processes:
            break
        time.sleep(.005)
    assert editor.processes
    editor.close()
    thread.join(timeout=2)
    assert not thread.is_alive() and failures
    assert not editor.processes


def test_routes_auth_upload_analysis_range_and_export(media, tmp_path, monkeypatch):
    _, original = media
    share = tmp_path / "recordings-share"
    share.mkdir()
    monkeypatch.setenv("VIDEO_EDITOR_EXPORT_VERIFY_DIR", str(share))

    def auth(value):
        if value != "Bearer test":
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(create_video_editor_router(tmp_path / "data", tmp_path, auth, lambda _: None))
    with TestClient(app) as client:
        assert client.post("/api/video-editor/sources", content=b"x").status_code == 401
        headers = {"Authorization": "Bearer test", "Content-Type": "video/mp4",
                   "X-Capture-Audio": '{"source":"device_playback","complete":true}'}
        response = client.post("/api/video-editor/sources", content=original.read_bytes(), headers=headers)
        assert response.status_code == 200, response.text
        identifier = response.json()["id"]
        for _ in range(1000):
            item = client.get(f"/api/video-editor/sources/{identifier}").json()
            if item["status"] in ("ready", "failed"):
                break
            time.sleep(.03)
        assert item["status"] == "ready", item
        assert item["audio_capture"]["complete"]
        ranged = client.get(item["url"], headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        assert client.get("/api/video-editor/sources/not-an-id").status_code == 404
        assert client.get(f"/api/video-editor/sources/{identifier}/record.json").status_code == 404
        job = client.post("/api/video-editor/exports", headers=headers,
                          json={"source_id": identifier, "in_s": 0, "out_s": 1, "include_audio": False}).json()
        for _ in range(1000):
            done = client.get(job["poll_url"]).json()
            if done["status"] in ("complete", "failed"):
                break
            time.sleep(.03)
        assert done["status"] == "complete", done
        exported = client.get(done["url"]).content
        assert exported[4:8] == b"ftyp"
        (share / done["name"]).write_bytes(exported)
        delivery = client.get(f"/api/video-editor/exports/{job['id']}/delivery").json()
        assert delivery["status"] == "delivered"
        assert delivery["verified"] == "sha256"
