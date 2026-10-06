import base64
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import pinelens


def relay():
    app = FastAPI()
    def auth(value):
        if value != "Bearer test":
            raise HTTPException(401, "Unauthorized")
    pinelens.install(app, {"require_auth": auth})
    return TestClient(app)


AUTH = {"Authorization": "Bearer test"}
FRAME = {"id": "f", "jpeg": base64.b64encode(b"\xff\xd8test\xff\xd9").decode()}


def exchange(client, revision="r", frame=FRAME, session="s"):
    body = {"session": session, "info": {"name": "Host", "control": True, "revision": revision}}
    if frame:
        body["frame"] = frame
    return client.post("/api/pinelens/hosts/h/exchange", json=body, headers=AUTH)


def test_desktop_pixels_and_commands_require_authentication():
    with relay() as client:
        assert client.get("/api/pinelens/hosts").status_code == 401
        assert exchange(client).status_code == 200
        assert client.get("/api/pinelens/hosts/h/view").status_code == 401
        assert client.post("/api/pinelens/hosts/h/command", json={"type": "full"}).status_code == 401


def test_view_demand_and_input_delivery_without_duplicate_execution():
    with relay() as client:
        assert exchange(client).json()["active"] is False
        view = client.get("/api/pinelens/hosts/h/view", headers=AUTH).json()
        assert view["frame"]["jpeg"] == FRAME["jpeg"]
        cmd = {"type": "pointer", "action": "down", "x": .25, "y": .75, "revision": "r"}
        assert client.post("/api/pinelens/hosts/h/command", json=cmd, headers=AUTH).status_code == 200
        out = exchange(client).json()
        assert out["active"] and out["commands"][0]["x"] == .25
        assert exchange(client).json()["commands"] == []


def test_crop_changes_and_host_restarts_invalidate_input():
    with relay() as client:
        exchange(client)
        exchange(client, revision="new", frame=None)
        assert client.get("/api/pinelens/hosts/h/view", headers=AUTH).json()["frame"] is None
        cmd = {"type": "text", "text": "old desktop", "revision": "r"}
        assert client.post("/api/pinelens/hosts/h/command", json=cmd, headers=AUTH).status_code == 409
        assert client.post("/api/pinelens/hosts/h/command", json={"type": "full"}, headers=AUTH).status_code == 200
        assert exchange(client, session="restarted").json()["commands"] == []


def test_stale_frames_and_queued_input_expire():
    with relay() as client, patch.object(pinelens.time, "monotonic", return_value=100) as clock:
        exchange(client)
        client.post("/api/pinelens/hosts/h/command", json={"type": "full"}, headers=AUTH)
        clock.return_value = 105
        assert client.get("/api/pinelens/hosts/h/view", headers=AUTH).json()["frame"] is None
        assert exchange(client).json()["commands"] == []


def test_input_outside_lens_and_shell_key_names_are_rejected():
    with relay() as client:
        exchange(client)
        for cmd in ({"type": "pointer", "action": "down", "x": -1, "y": .5},
                    {"type": "key", "key": "$(touch injected)"}):
            assert client.post("/api/pinelens/hosts/h/command", json={**cmd, "revision": "r"}, headers=AUTH).status_code == 400


def test_export_uses_viewed_recording_host_and_survives_input_queue_expiry():
    with relay() as client, patch.object(pinelens.time, "monotonic", return_value=100) as clock:
        for identifier in ("pc1", "pc2"):
            client.post(f"/api/pinelens/hosts/{identifier}/exchange", headers=AUTH,
                        json={"session": identifier, "info": {"name": identifier, "recording": True}})
        client.get("/api/pinelens/hosts/pc2/view", headers=AUTH)
        assert client.post("/api/pinelens/export", json={"seconds": 300}).status_code == 401
        job = client.post("/api/pinelens/export", headers=AUTH, json={"seconds": 300}).json()
        assert job["host"] == "pc2"
        clock.return_value = 105
        def poll(identifier):
            return client.post(f"/api/pinelens/hosts/{identifier}/exchange", headers=AUTH,
                               json={"session": identifier, "info": {"recording": True}}).json()
        assert poll("pc1")["exports"] == []
        assert poll("pc2")["exports"] == [{"id": job["id"], "seconds": 300}]
        assert client.post("/api/pinelens/export", headers=AUTH, json={"seconds": 60}).status_code == 409
        done = {"id": job["id"], "session": "pc1", "state": "done"}
        assert client.post("/api/pinelens/hosts/pc1/export-done", headers=AUTH, json=done).status_code == 409
        done.update(session="pc2", seconds=180, partial=True)
        assert client.post("/api/pinelens/hosts/pc2/export-done", headers=AUTH, json=done).status_code == 200
        state = client.get(f"/api/pinelens/export/{job['id']}", headers=AUTH).json()
        assert state["state"] == "done" and state["result"]["partial"]
        assert "session" not in state
        assert poll("pc2")["exports"] == []


def test_export_requires_live_recording_and_does_not_select_an_unrelated_host():
    with relay() as client:
        exchange(client)
        assert client.post("/api/pinelens/export", headers=AUTH, json={"seconds": 300}).status_code == 409
        for seconds in (-1, "oops"):
            assert client.post("/api/pinelens/export", headers=AUTH, json={"seconds": seconds}).status_code == 400


def test_desktop_restart_reports_failed_export_instead_of_leaving_it_queued():
    with relay() as client:
        client.post("/api/pinelens/hosts/h/exchange", headers=AUTH,
                    json={"session": "old", "info": {"recording": True}})
        job = client.post("/api/pinelens/export", headers=AUTH, json={"seconds": 60}).json()
        exchange(client, session="new")
        state = client.get(f"/api/pinelens/export/{job['id']}", headers=AUTH).json()
        assert state["state"] == "failed"
        assert "restarted" in state["result"]["error"]
