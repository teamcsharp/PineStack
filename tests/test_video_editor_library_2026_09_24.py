"""The splice media bin searches local indexed metadata, never the share."""
import ast
from pathlib import Path
import re
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_search(connection):
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "video_editor_library_search")
    namespace = {
        "Any": Any,
        "re": re,
        "sfx_db_reader": lambda: connection,
        "media_sign": lambda sid: "signed-" + sid,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"),
         namespace)
    return namespace["video_editor_library_search"]


def test_library_searches_name_folder_spoken_and_visual_topic():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE clips (
        sid TEXT, name TEXT, folder TEXT, seconds REAL, playable INTEGER,
        video INTEGER, seen_at REAL, said TEXT, seen_desc TEXT)""")
    rows = [
        ("a" * 16, "market report", "news", 4.2, 1, 1, 3,
         "the dow is down", "financial anchor at a desk"),
        ("b" * 16, "kitchen cut", "food", 6.0, 1, 1, 2,
         "plate the fish", "chef cooking dinner"),
        ("c" * 16, "audio only", "news", 2.0, 1, 0, 4, "dow", ""),
    ]
    connection.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?)", rows)
    search = load_search(connection)
    found = search("dow financial news", 20)
    assert [row["id"] for row in found] == ["a" * 16]
    assert found[0]["spoken"] == "the dow is down"
    assert found[0]["topic"] == "financial anchor at a desk"
    assert "path" not in found[0]
    assert found[0]["poster_url"].startswith("/api/sfx/poster/")


def test_library_search_tolerates_books_without_analysis_columns():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE clips (
        sid TEXT, name TEXT, folder TEXT, seconds REAL, playable INTEGER,
        video INTEGER, seen_at REAL)""")
    connection.execute("INSERT INTO clips VALUES (?,?,?,?,?,?,?)",
                       ("d" * 16, "station ident", "sfx_ads", 3, 1, 1, 1))
    found = load_search(connection)("station sfx_ads", 10)
    assert len(found) == 1
    assert found[0]["spoken"] == found[0]["topic"] == ""
