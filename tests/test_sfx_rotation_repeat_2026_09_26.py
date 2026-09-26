"""Isolated regression checks without starting station workers."""
import ast
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def extracted(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def test_short_videos_use_unspent_folders_and_respect_pin():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE clips(path,seconds,playable,video,deck_cycle,folder)")
    db.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?)", [
        ("/clips/big/a.mp4", 3, 1, 1, 0, "big"),
        ("/clips/deep/rare/b.mp4", 5, 1, 1, 0, "rare"),
        ("/clips/spent/c.mp4", 3, 1, 1, 2, "spent"),
        ("/clips/rare/long.mp4", 90, 1, 1, 0, "rare"),
    ])
    pin = [""]
    ns = dict(Path=Path, Any=object, random=random, sfx_db_reader=lambda: db,
              sfx_video_rotation_cycle=lambda: 2, sfx_video_recent_folders=lambda: ["big"],
              sfx_pin_prefix=lambda: pin[0])
    pick = extracted(ROOT / "app.py", "sfx_db_pick_short_video", ns)
    assert pick(12) == (Path("/clips/deep/rare/b.mp4"), 5)
    pin[0] = "/clips/big/"
    assert pick(12) == (Path("/clips/big/a.mp4"), 3)
    pin[0] = "/clips/spent/"
    assert pick(12) is None
    db.close()


def test_one_repeated_line_cannot_ride_with_fresh_dialogue():
    check = extracted(ROOT / "system2_runtime.py", "repeat_allowed", {})
    store = SimpleNamespace(can_play=Mock(return_value={"allowed": False, "reason": "heard_within_one_hour"}))
    runtime = SimpleNamespace(content_gate_enabled=lambda gate: True, store=store,
                              host=SimpleNamespace(pipeline_log=Mock()))
    assert check(runtime, ["Already heard", "New line", "Another new line"]) is False
    store.can_play.return_value = {"allowed": True}
    assert check(runtime, ["Entirely fresh"]) is True


def test_banked_cues_do_not_override_video_share():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "_sfx_cadence_additions_inner")
    assignments = [n for n in ast.walk(node) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "requested_video" for t in n.targets)]
    assert len(assignments) == 1
    assert not isinstance(assignments[0].value, ast.Constant)
