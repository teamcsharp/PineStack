import asyncio

import pytest

import app


def test_sfx_url_is_constant_time_signing_without_library_lookup(monkeypatch):
    monkeypatch.setattr(app, "require_read_auth", lambda value: None)
    monkeypatch.setattr(app, "media_sign", lambda value: "signed-" + value)

    got = asyncio.run(app.sfx_url_api(id="clip-42", authorization="test"))

    assert got == {
        "id": "clip-42",
        "url": "/sfx/clip-42?t=signed-clip-42",
        "video": True,
    }


@pytest.mark.parametrize("sample_id", ["", "../clip", "clip?raw=1", "clip#x"])
def test_sfx_url_rejects_non_ids(monkeypatch, sample_id):
    monkeypatch.setattr(app, "require_read_auth", lambda value: None)

    with pytest.raises(app.HTTPException) as raised:
        asyncio.run(app.sfx_url_api(id=sample_id, authorization="test"))

    assert raised.value.status_code == 400
