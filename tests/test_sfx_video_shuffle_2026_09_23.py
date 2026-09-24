import asyncio

import app


def test_shuffle_rebuilds_indexes_excludes_recent_and_returns_unique_batch(monkeypatch):
    excluded = ["0123456789abcdef", "fedcba9876543210"]
    rows = iter([
        {"id": "aaaaaaaaaaaaaaaa", "url": "/sfx/a"},
        {"id": "aaaaaaaaaaaaaaaa", "url": "/sfx/a"},
        {"id": "bbbbbbbbbbbbbbbb", "url": "/sfx/b"},
        {"id": "cccccccccccccccc", "url": "/sfx/c"},
    ])
    cooled = []
    actions = []
    calls = []

    async def cue(payload, authorization):
        calls.append((payload, authorization))
        try:
            return {"ok": True, "clip": next(rows)}
        except StopIteration:
            return {"ok": False}

    monkeypatch.setattr(app, "require_auth", lambda value: None)
    monkeypatch.setattr(app, "sfx_video_reserve_many", lambda values: cooled.extend(values))
    monkeypatch.setattr(app, "sfx_all_index_reset", lambda: actions.append("all"))
    monkeypatch.setattr(app, "sfx_video_kick", lambda: actions.append("video"))
    monkeypatch.setattr(app, "sfx_db_kick", lambda force=False: True)
    monkeypatch.setattr(app, "sfx_video_cue_api", cue)
    monkeypatch.setattr(app, "note_action", actions.append)
    monkeypatch.setattr(app, "_SFX_POOL_SIGNATURE", ["old"])
    monkeypatch.setattr(app, "_SFX_VIDEO_MEMO", {"old": True})
    monkeypatch.setattr(app, "_SFX_ID_MEMO", {"old": True})
    monkeypatch.setattr(app, "_SFX_ID_REVERSE", {"old": True})
    monkeypatch.setattr(app, "_SFX_POOL_IDS", {"old": True})
    monkeypatch.setattr(app, "_SFX_DB_SCAN", {"running": True, "scanned": 12})
    monkeypatch.setattr(app, "_SFX_CYCLE", {"shuffle_epoch": 4})
    monkeypatch.setattr(app, "_RADIO", {"voice_clips": [
        {"id": "old", "endless": True, "broadcast_ms": 9999999999999},
        {"id": "manual", "broadcast_ms": 9999999999999},
    ]})
    monkeypatch.setattr(app, "sfx_video_cooldown_state", lambda: {
        "rotation": {"cycle": 7, "used": 12}})

    got = asyncio.run(app.sfx_video_shuffle_api(
        {"exclude": excluded, "most": 3}, "Bearer test"))

    assert got["ok"] is True
    assert got["excluded"] == 2
    assert got["scan_started"] is True
    assert [row["id"] for row in got["clips"]] == [
        "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"]
    assert set(cooled) == set(excluded)
    assert app._SFX_CYCLE["shuffle_epoch"] == 5
    assert [row["id"] for row in app._RADIO["voice_clips"]] == ["manual"]
    assert got["rotation"] == {"cycle": 7, "used": 12}
    assert app._SFX_POOL_SIGNATURE == [None]
    assert app._SFX_ID_MEMO == {}
    assert app._SFX_ID_REVERSE == {}
    assert app._SFX_POOL_IDS == {"key": None, "map": {}}
    assert calls and all(call == ({"who": "shuffle"}, "Bearer test") for call in calls)
    assert any("3 new clips" in str(action) for action in actions)


def test_shuffle_ignores_non_list_exclusions(monkeypatch):
    async def cue(payload, authorization):
        return {"ok": False}

    monkeypatch.setattr(app, "require_auth", lambda value: None)
    monkeypatch.setattr(app, "sfx_video_reserve_many",
                        lambda value: (_ for _ in ()).throw(AssertionError(value)))
    monkeypatch.setattr(app, "sfx_all_index_reset", lambda: None)
    monkeypatch.setattr(app, "sfx_video_kick", lambda: None)
    monkeypatch.setattr(app, "sfx_db_kick", lambda force=False: False)
    monkeypatch.setattr(app, "sfx_video_cue_api", cue)
    monkeypatch.setattr(app, "note_action", lambda value: None)
    monkeypatch.setattr(app, "_SFX_POOL_SIGNATURE", ["old"])
    monkeypatch.setattr(app, "_SFX_VIDEO_MEMO", {})
    monkeypatch.setattr(app, "_SFX_ID_MEMO", {})
    monkeypatch.setattr(app, "_SFX_ID_REVERSE", {})
    monkeypatch.setattr(app, "_SFX_POOL_IDS", {})
    monkeypatch.setattr(app, "_SFX_DB_SCAN", {})
    monkeypatch.setattr(app, "_SFX_CYCLE", {})
    monkeypatch.setattr(app, "_RADIO", {"voice_clips": []})
    monkeypatch.setattr(app, "sfx_video_cooldown_state", lambda: {"rotation": {}})

    got = asyncio.run(app.sfx_video_shuffle_api(
        {"exclude": "0123456789abcdef", "most": 3}, "Bearer test"))

    assert got["excluded"] == 0
    assert got["clips"] == []


def test_rotation_picker_is_random_only_within_unspent_rows(monkeypatch, tmp_path):
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE clips (
        path TEXT, sid TEXT, folder TEXT, video INTEGER, playable INTEGER,
        seconds REAL, deck_cycle INTEGER)""")
    rows = [
        (str(tmp_path / "old" / "a.mp4"), "a" * 16, "old", 1, 1, 4.0, 3),
        (str(tmp_path / "fresh" / "b.mp4"), "b" * 16, "fresh", 1, 1, 5.0, 2),
        (str(tmp_path / "other" / "c.mp4"), "c" * 16, "other", 1, 1, 6.0, 2),
    ]
    con.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?)", rows)
    monkeypatch.setattr(app, "sfx_db_reader", lambda: con)
    monkeypatch.setattr(app, "sfx_video_rotation_cycle", lambda: 3)
    monkeypatch.setattr(app, "sfx_video_recent_folders", lambda: ["fresh"])
    monkeypatch.setattr(app, "sfx_pin_prefix", lambda: "")
    monkeypatch.setattr(app, "dj_settings", lambda: {"sfx_video_len": 0})

    for _ in range(12):
        got = app.sfx_db_pick_rotation_row(True)
        assert got is not None
        assert got[0].name == "c.mp4"


def test_rotation_picker_falls_back_to_recent_folder_before_repeating_clip(
        monkeypatch, tmp_path):
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE clips (
        path TEXT, sid TEXT, folder TEXT, video INTEGER, playable INTEGER,
        seconds REAL, deck_cycle INTEGER)""")
    con.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?)", [
        (str(tmp_path / "same" / "spent.mp4"), "a" * 16, "same", 1, 1, 4.0, 9),
        (str(tmp_path / "same" / "fresh.mp4"), "b" * 16, "same", 1, 1, 5.0, 8),
    ])
    monkeypatch.setattr(app, "sfx_db_reader", lambda: con)
    monkeypatch.setattr(app, "sfx_video_rotation_cycle", lambda: 9)
    monkeypatch.setattr(app, "sfx_video_recent_folders", lambda: ["same"])
    monkeypatch.setattr(app, "sfx_pin_prefix", lambda: "")
    monkeypatch.setattr(app, "dj_settings", lambda: {"sfx_video_len": 0})

    got = app.sfx_db_pick_rotation_row(True)
    assert got is not None
    assert got[0].name == "fresh.mp4"


def test_rotation_spends_same_title_and_byte_identical_video_families(monkeypatch):
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE clips (
        sid TEXT, name TEXT, folder TEXT, video INTEGER, bytes INTEGER,
        seconds REAL, deck_cycle INTEGER)""")
    con.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?)", [
        ("a" * 16, "12 clip-110", "rasslin", 1, 1400930, 17.648, 0),
        ("b" * 16, "12 clip-110", "deadwood", 1, 900000, 7.1, 0),
        ("c" * 16, "renamed copy", "other", 1, 1400930, 17.648, 0),
        ("d" * 16, "12 clip-110", "audio", 0, 1400930, 17.648, 0),
        ("e" * 16, "different clip", "other", 1, 123, 4.0, 0),
    ])
    monkeypatch.setattr(app, "sfx_db", lambda: con)
    monkeypatch.setattr(app, "_SFX_VIDEO_ROTATION", {
        "ready": True, "cycle": 7, "used": set(), "folders": [],
        "resets": 0, "why": "", "picked": 0,
    })

    app._sfx_video_rotation_mark_clip("a" * 16, "rasslin")

    spent = {row["sid"] for row in con.execute(
        "SELECT sid FROM clips WHERE deck_cycle = 7")}
    assert spent == {"a" * 16, "b" * 16, "c" * 16}
    assert "d" * 16 not in spent
    assert "e" * 16 not in spent
    assert app._SFX_VIDEO_ROTATION["used"] == spent
    assert app._SFX_VIDEO_ROTATION["folders"] == ["rasslin"]


def test_shuffle_reservations_use_visible_title_family_road(monkeypatch):
    marked = []
    monkeypatch.setattr(app, "_sfx_video_played_load", lambda: None)
    monkeypatch.setattr(app, "_sfx_video_played_save", lambda: None)
    monkeypatch.setattr(app, "_sfx_video_rotation_mark_clip", marked.append)
    monkeypatch.setattr(app, "_SFX_VIDEO_PLAYED", {})
    monkeypatch.setattr(app, "_SFX_VIDEO_PLAYED_DIRTY", [0])

    app.sfx_video_reserve_many(["a" * 16, "b" * 16, "a" * 16])

    assert marked == ["a" * 16, "b" * 16]
