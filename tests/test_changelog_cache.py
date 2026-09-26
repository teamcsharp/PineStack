from __future__ import annotations

import json

from changelog import ChangeLog


def _entries() -> list[dict[str, object]]:
    return [
        {
            "commit": "a" * 40,
            "short": "a" * 7,
            "date": "2026-09-26T12:00:00-05:00",
            "subject": "Newest",
            "task": {},
        },
        {
            "commit": "b" * 40,
            "short": "b" * 7,
            "date": "2026-09-25T12:00:00-05:00",
            "subject": "Older",
            "task": {},
        },
    ]


def test_page_uses_durable_cache_without_git(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    cache = tmp_path / "cache.json"
    first = ChangeLog(tmp_path, tasks, cache)
    monkeypatch.setattr(first, "_git_entries", lambda limit, before="": _entries())
    first.refresh()

    restored = ChangeLog(tmp_path, tasks, cache)
    monkeypatch.setattr(
        restored,
        "_git_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Git was queried")),
    )
    page = restored.page(limit=1)

    assert page["entries"][0]["subject"] == "Newest"
    assert page["has_more"] is True
    assert page["stale"] is False


def test_existing_rich_cache_paginates_by_completion_timestamp(tmp_path):
    tasks = tmp_path / "tasks.json"
    cache = tmp_path / "cache.json"
    rows = _entries()
    rows[0]["completed_at"] = 200.0
    rows[0]["task_name"] = "Newest rich entry"
    rows[1]["completed_at"] = 100.0
    rows[1]["task_name"] = "Older rich entry"
    cache.write_text(json.dumps({"head": rows[0]["commit"], "entries": rows}), "utf-8")

    page = ChangeLog(tmp_path, tasks, cache).page(limit=1)
    older = ChangeLog(tmp_path, tasks, cache).page(limit=1, before=page["next_before"])

    assert page["entries"][0]["task_name"] == "Newest rich entry"
    assert older["entries"][0]["task_name"] == "Older rich entry"


def test_task_annotation_is_written_into_cached_snapshot(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    cache = tmp_path / "cache.json"
    changelog = ChangeLog(tmp_path, tasks, cache)
    monkeypatch.setattr(changelog, "_git_entries", lambda limit, before="": _entries())
    changelog.refresh()

    changelog.record("a" * 40, {"goal": "Keep the station available"})

    stored = json.loads(cache.read_text("utf-8"))
    assert stored["entries"][0]["task"]["goal"] == "Keep the station available"
    assert ChangeLog(tmp_path, tasks, cache).page()["entries"][0]["task"]["goal"] == "Keep the station available"


def test_explicit_refresh_preserves_history_and_rich_details(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    rows = _entries()
    rows[0]["task_name"] = "Detailed title"
    rows[0]["files"] = [{"path": "app.py", "added": 8}]
    cache.write_text(json.dumps({"entries": rows}), "utf-8")
    changelog = ChangeLog(tmp_path, tmp_path / "tasks.json", cache)
    monkeypatch.setattr(changelog, "_git_entries", lambda *_args: _entries()[:1])

    page = changelog.refresh(limit=1)

    assert page["total"] == 2
    assert page["entries"][0]["task_name"] == "Detailed title"
    assert page["entries"][0]["files"] == rows[0]["files"]
    assert page["entries"][1]["commit"] == rows[1]["commit"]


def test_failed_refresh_leaves_snapshot_readable(tmp_path, monkeypatch):
    import pytest

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"entries": _entries()}), "utf-8")
    changelog = ChangeLog(tmp_path, tmp_path / "tasks.json", cache)
    def unavailable(*_args):
        raise RuntimeError("dubious ownership")
    monkeypatch.setattr(changelog, "_git_entries", unavailable)
    with pytest.raises(RuntimeError):
        changelog.refresh()
    assert len(changelog.page()["entries"]) == 2
    assert len(ChangeLog(tmp_path, tmp_path / "tasks.json", cache).page()["entries"]) == 2
