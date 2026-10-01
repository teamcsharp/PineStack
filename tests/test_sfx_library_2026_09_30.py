"""[sfx-library] the SFX Guy's database as a searchable, editable table.

"at the top put a search bar, I want to type anything and have it be looked up
by the database showing suggestions ... search for anything that is used as a
tag in the database and search by clip name, folder, source, identified media
tag, and any parameter that is used in the database."
"""
import tempfile
import unittest
from pathlib import Path

import sfx_library as lib
import sfx_vectors
from test_sfx_vectors import CLIPS, fill


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.store = sfx_vectors.Store(Path(self.tmp.name) / "section",
                                       roots={"samples": "/samples", "made": "/app/data/sfx"})
        self.addCleanup(self.store.close)
        fill(self.store)
        self.con = self.store.con

    def sids(self, q):
        return sorted(r["sid"] for r in lib.search(self.con, q, limit=100)["rows"])

    def test_parse_keeps_free_words_and_fields(self):
        text, f = lib.parse('dog tag:funny seconds:<5 "big crash" folder:"my clips" nofield:x')
        self.assertEqual(text, "dog big crash nofield:x")
        self.assertEqual(f, [("tag", "funny"), ("seconds", "<5"), ("folder", "my clips")])

    def test_free_words_reach_name_said_seen_and_folder(self):
        self.assertEqual(self.sids("sewer"), ["c1"])           # name and said
        self.assertEqual(self.sids("neon"), ["c3"])            # what the vision pass saw
        self.assertEqual(self.sids("iasip"), ["c3"])           # folder
        self.assertEqual(self.sids("samples"), ["c1", "c2", "c3", "c5"])   # source

    def test_every_parameter_narrows(self):
        self.assertEqual(self.sids("video:yes"), ["c1", "c3", "c5"])
        self.assertEqual(self.sids("video:no"), ["c2", "c4"])
        self.assertEqual(self.sids("seconds:<4"), ["c2", "c4"])
        self.assertEqual(self.sids("seconds:5-6"), ["c1", "c5"])
        self.assertEqual(self.sids("folder:tiktok video:yes"), ["c1", "c5"])
        self.assertEqual(self.sids("source:made"), ["c4"])
        self.assertEqual(self.sids("seen:crowd"), ["c3"])
        self.assertEqual(self.sids("said:scream"), ["c2"])
        self.assertEqual(self.sids("aired:0"), ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual(self.sids("id:c4"), ["c4"])

    def test_a_tag_searches_and_suggests(self):
        self.assertTrue(lib.tag_add(self.con, "c5", "visual", "red car"))
        self.assertEqual(self.sids("tag:red"), ["c5"])
        self.assertEqual(self.sids('visual:"red car"'), ["c5"])
        self.assertEqual(self.sids("red"), ["c5"])               # the full-text index carries tags
        got = lib.suggest(self.con, "red")
        tag = [s for s in got if s["group"] == "tag" and s["label"] == "red car"]
        self.assertTrue(tag)
        self.assertEqual(tag[0]["token"], 'tag:"red car"')
        self.assertEqual(self.sids(tag[0]["token"]), ["c5"])

    def test_suggestions_cover_parameters_folders_sources_clips_and_seen(self):
        groups = {s["group"] for s in lib.suggest(self.con, "t")}
        self.assertIn("folder", groups)
        self.assertIn("parameter", groups)                    # tag:, tagged:, theme:
        self.assertIn("clip", {s["group"] for s in lib.suggest(self.con, "party")})
        self.assertIn("seen", {s["group"] for s in lib.suggest(self.con, "neon")})
        self.assertIn("source", {s["group"] for s in lib.suggest(self.con, "samp")})
        only = lib.suggest(self.con, "folder:ti")
        self.assertTrue(only and all(s["group"] == "folder" for s in only))
        self.assertTrue(lib.suggest(self.con, "said:dance"))

    def test_the_operators_tag_outlives_the_keeper_and_new_words(self):
        lib.tag_add(self.con, "c1", "theme", "rescue")
        self.store.retag_all()
        self.store.tag_clips(limit=100, floor=0.0, per_facet=2)
        self.assertEqual(self.sids("tag:rescue"), ["c1"])
        changed = dict(CLIPS[0], said="a completely different line now")
        self.store.upsert_clips([changed])                    # the words changed: the keeper's tags go
        rows = self.con.execute("select tag, how from facet_tags where sid='c1'").fetchall()
        self.assertEqual(rows, [("rescue", "operator")])
        self.assertEqual(self.sids("rescue"), ["c1"])
        self.assertTrue(lib.tag_remove(self.con, "c1", "theme", "rescue"))
        self.assertEqual(self.sids("tag:rescue"), [])

    def test_bad_input_is_not_an_error(self):
        for q in ('"unclosed', "*", "seconds:abc", "tag:", ":::", "NEAR(", "a AND OR"):
            lib.search(self.con, q)
            lib.suggest(self.con, q)

    def test_export_csv_and_json(self):
        rows = lib.search(self.con, "tiktok")["rows"]
        csv_text = lib.export_text(rows, "csv")
        self.assertTrue(csv_text.startswith("sid,name,folder"))
        self.assertEqual(csv_text.count("\n"), len(rows) + 1)
        self.assertIn('"sid"', lib.export_text(rows, "json"))


if __name__ == "__main__":
    unittest.main()


class FileState(unittest.TestCase):
    """[sfx-gone] a clip the book lists but the share does not hold."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "samples"
        (self.root / "Rest").mkdir(parents=True)
        self.here = self.root / "Rest" / "a.mp4"
        self.here.write_bytes(b"x")

    def test_here_gone_and_unreachable(self):
        self.assertEqual(lib.file_state(self.here, [self.root]), "here")
        self.assertEqual(lib.file_state(self.root / "Rest" / "b.mp4", [self.root]), "gone")
        self.assertEqual(lib.file_state(self.root / "Gone" / "b.mp4", [self.root]), "gone")

    def test_an_unmounted_share_never_says_gone(self):
        away = Path(self.tmp.name) / "unmounted"
        self.assertEqual(lib.file_state(away / "Rest" / "b.mp4", [away]), "unreachable")
        away.mkdir()                                  # a mount point with nothing in it
        self.assertEqual(lib.file_state(away / "Rest" / "b.mp4", [away]), "unreachable")
        self.assertEqual(lib.file_state("", [self.root]), "unreachable")
