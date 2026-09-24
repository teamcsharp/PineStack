"""Gallery export through the real HTTP routes and courier ledger."""
import io
import zipfile

from fastapi.testclient import TestClient
import pytest

import app as station


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    original = tmp_path / "source.mp4"
    generated = tmp_path / "render.mp4"
    original.write_bytes(b"original-video")
    generated.write_bytes(b"generated-video")
    row = {"prompt_id": "ticket", "files": ["render.mp4"],
           "source_type": "clip", "source": "source-id"}

    def resolve(kind, key):
        if (kind, key) == ("clip", "source-id"):
            return original, "video"
        if (kind, key) == ("generation", "render.mp4"):
            return generated, "video"
        raise FileNotFoundError("Media is gone")

    real_data_path = station.data_path
    monkeypatch.setattr(station, "workshop_generation",
                        lambda ticket: row if ticket == "ticket" else None)
    monkeypatch.setattr(station, "workshop_source_path", resolve)
    monkeypatch.setattr(station, "require_auth", lambda _auth: None)
    monkeypatch.setattr(station, "require_read_auth", lambda _auth: None)
    monkeypatch.setattr(station, "SPARK_AGENT_API_KEY", "gallery-export-test-key")
    monkeypatch.setattr(station, "pipeline_log", lambda *_args: None)
    monkeypatch.setattr(station, "EXPORT_COURIER_PATH", tmp_path / "courier.json")
    monkeypatch.setattr(station, "data_path",
                        lambda key: tmp_path / "gallery-stage"
                        if key == "exports/gallery" else real_data_path(key))
    return TestClient(station.app), row, original, generated


@pytest.mark.parametrize("scope,expected", [
    ("original", b"original-video"),
    ("generated", b"generated-video"),
])
def test_device_exports_exact_media_and_custom_name(gallery, scope, expected):
    client, _row, _original, _generated = gallery
    prepared = client.post("/api/gallery/export", json={
        "prompt_id": "ticket", "file": "render.mp4", "scope": scope,
        "destination": "device", "name": "My gallery take"})
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["name"] == "My gallery take.mp4"
    download = client.get(prepared.json()["url"])
    assert download.status_code == 200, download.text
    assert download.content == expected
    assert "My%20gallery%20take.mp4" in download.headers["content-disposition"]
    assert client.get(prepared.json()["url"].replace("t=", "t=wrong")).status_code == 403


def test_both_download_and_share_copy_preserve_original_bytes(gallery):
    client, _row, original, generated = gallery
    body = {"prompt_id": "ticket", "file": "render.mp4", "scope": "both",
            "name": "Two takes"}
    prepared = client.post("/api/gallery/export", json={**body,
                            "destination": "device"})
    assert prepared.status_code == 200, prepared.text
    download = client.get(prepared.json()["url"])
    assert download.status_code == 200, download.text
    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
        assert bundle.namelist() == ["Two takes-original.mp4",
                                     "Two takes-generated.mp4"]
        assert bundle.read("Two takes-original.mp4") == original.read_bytes()
        assert bundle.read("Two takes-generated.mp4") == generated.read_bytes()

    first = client.post("/api/gallery/export", json={**body,
                        "destination": "share"})
    assert first.status_code == 200, first.text
    assert first.json()["destination"] == station.GALLERY_EXPORT_SHARE
    job = station.courier_read()[0]
    assert job["name"] == "Two takes.zip" and job["force"] is True
    assert job["state"] == "pending"
    carried = client.get("/api/export/courier/" + job["id"] + "/file")
    assert carried.content == download.content

    generated.write_bytes(b"generated-update")
    second = client.post("/api/gallery/export", json={**body,
                         "destination": "share"})
    assert second.status_code == 200, second.text
    jobs = station.courier_read()
    assert len(jobs) == 2 and jobs[0]["path"] != jobs[1]["path"]
    with zipfile.ZipFile(jobs[1]["path"]) as bundle:
        assert bundle.read("Two takes-generated.mp4") == b"generated-update"


def test_invalid_and_missing_media_never_queue_courier_work(gallery):
    client, row, _original, _generated = gallery
    base = {"prompt_id": "ticket", "file": "render.mp4",
            "scope": "generated", "destination": "share", "name": "take"}
    for change, status in [
        ({"name": "../outside"}, 400),
        ({"name": "CON"}, 400),
        ({"scope": "neither"}, 400),
        ({"file": "other.mp4"}, 400),
    ]:
        assert client.post("/api/gallery/export",
                           json={**base, **change}).status_code == status
    row["source"] = ""
    assert client.post("/api/gallery/export", json={**base,
                       "scope": "original"}).status_code == 409
    assert station.courier_read() == []


def test_image_pair_and_untracked_gallery_still(gallery, tmp_path, monkeypatch):
    client, row, _original, _generated = gallery
    source = tmp_path / "reference.jpg"
    made = tmp_path / "painting.png"
    source.write_bytes(b"reference-image")
    made.write_bytes(b"generated-image")
    row.update(files=["painting.png"], source_type="gallery",
               source="reference.jpg")

    def resolve(kind, key):
        if (kind, key) == ("gallery", "reference.jpg"):
            return source, "image"
        if (kind, key) == ("generation", "painting.png"):
            return made, "image"
        raise FileNotFoundError("Media is gone")

    monkeypatch.setattr(station, "workshop_source_path", resolve)
    pair = client.post("/api/gallery/export", json={
        "prompt_id": "ticket", "file": "painting.png", "scope": "both",
        "destination": "device", "name": "Gallery art"})
    assert pair.status_code == 200, pair.text
    with zipfile.ZipFile(io.BytesIO(client.get(pair.json()["url"]).content)) as bundle:
        assert bundle.namelist() == ["Gallery art-original.jpg",
                                     "Gallery art-generated.png"]
        assert bundle.read("Gallery art-original.jpg") == b"reference-image"
        assert bundle.read("Gallery art-generated.png") == b"generated-image"

    untracked = client.post("/api/gallery/export", json={
        "file": "painting.png", "scope": "generated", "destination": "device",
        "name": "Standalone"})
    assert untracked.status_code == 200, untracked.text
    assert client.get(untracked.json()["url"]).content == b"generated-image"
