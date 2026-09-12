"""#1240: the slideshow's folder, its likes and its settings, read from here.

`~/bin/media-slideshow` is 25,000 lines of PySide6 on the box's own glass.
The tablet cannot run any of it, so the station reads what it reads and the
tablet draws it. That only works while the two agree about three files, and
each of these tests pins one of the three:

  * favorites.md — class Favorites writes it NEXT TO THE MEDIA, which is
    inside the /comfy-output bind mount, so this process genuinely shares
    it. Both applications write the whole file on every toggle, so the
    format has to match byte for byte or the file churns and a diff stops
    meaning anything.

  * screensaver_state.json — the desktop app persists keys this one has no
    opinion about (the two dragged diagnostic circles, the service panel's
    colours). A write from the tablet MERGES, or the box's next launch comes
    up having quietly lost them.

  * the transition list — the tablet cycles it and the station refuses
    anything not in it. A disagreement is a setting written on one screen
    that the other cannot show.

The shuffle test is here for a different reason: the desktop app's Playlist
is a shuffled rotation, and a paged API that re-deals per page would hand
the tablet the same picture twice and skip others entirely.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class SlideshowFolderTests(unittest.TestCase):
    def test_kind_matches_the_desktop_extension_sets(self):
        self.assertEqual(app._slideshow_kind("a.PNG"), "image")
        self.assertEqual(app._slideshow_kind("a.tiff"), "image")
        self.assertEqual(app._slideshow_kind("a.mkv"), "video")
        self.assertEqual(app._slideshow_kind("a.m4v"), "video")
        # Not playable, and the desktop app does not show them either.
        self.assertEqual(app._slideshow_kind("favorites.md"), "")
        self.assertEqual(app._slideshow_kind("a.txt"), "")
        # A dotfile named for an extension is a STEM, not a suffix. The older
        # lock-screen route used endswith() and counted one of these as a
        # picture, which is the whole of its one-file disagreement with this
        # scan.
        self.assertEqual(app._slideshow_kind(".png"), "")

    def test_the_transition_list_is_the_desktop_app_s_own(self):
        # Copied from media-slideshow's TRANSITIONS (its line 263), in its
        # order. "all" is first because it is the default and means "pick a
        # concrete one per advance".
        self.assertEqual(app.SLIDESHOW_TRANSITIONS, [
            "all", "slide", "swirl", "rotate", "flip", "mosaic", "fold",
            "bump", "bash", "unroll", "origami", "sand", "shatter", "cube",
            "delete", "tv", "crt", "vaporwave", "unfold", "liquid",
        ])


class SlideshowFavoritesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.object(app, "SLIDESHOW_ROOT", self.root)
        self.patch.start()
        for name in ("a.png", "b.png", "c.png"):
            (self.root / name).write_bytes(b"x")

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write(self, text):
        (self.root / "favorites.md").write_text(text, encoding="utf-8")

    def test_all_three_shapes_the_desktop_reader_accepts(self):
        # class Favorites.reload() takes a markdown link, a bare list item
        # and a plain line, because its own writer has changed shape over
        # time and a human edits this file. All three are read here too.
        self.write("# Favorites\n\n- [a.png](a.png)\n- b.png\nc.png\n")
        self.assertEqual(app._slideshow_favorites_read_blocking(),
                         {"a.png", "b.png", "c.png"})

    def test_an_absolute_host_path_is_the_same_picture(self):
        # The desktop app writes relative paths, but a hand-edited file may
        # carry the host's absolute one - which is this same file seen from
        # the other side of the bind mount.
        self.write("- [a.png](/home/ehm_eckx/ComfyUI/output/a.png)\n")
        self.assertEqual(app._slideshow_favorites_read_blocking(), {"a.png"})

    def test_a_favourite_that_no_longer_exists_is_dropped(self):
        # The desktop resolves each entry and keeps only what is on disk. A
        # tablet showing favourites the box has deleted would be worse than
        # one showing none.
        self.write("- [a.png](a.png)\n- [gone.png](gone.png)\n")
        self.assertEqual(app._slideshow_favorites_read_blocking(), {"a.png"})

    def test_comments_and_blank_lines_are_not_filenames(self):
        self.write("# Favorites\n\nEdited by media-slideshow. One file per "
                   "line.\n\n- [a.png](a.png)\n")
        # The prose line is not a path and must not become one.
        self.assertEqual(app._slideshow_favorites_read_blocking(), {"a.png"})

    def test_the_file_written_is_byte_identical_to_the_desktop_app_s(self):
        # This is the format class Favorites._write produces, exactly. Both
        # programs rewrite the whole file on every toggle; a different header
        # or link shape would make the file churn between them.
        app._slideshow_favorites_write_blocking({"b.png", "a.png"})
        self.assertEqual(
            (self.root / "favorites.md").read_text(encoding="utf-8"),
            "# Favorites\n"
            "\n"
            "Edited by media-slideshow. One file per line.\n"
            "\n"
            "- [a.png](a.png)\n"
            "- [b.png](b.png)\n")

    def test_a_write_then_a_read_is_the_same_set(self):
        app._slideshow_favorites_write_blocking({"c.png", "a.png"})
        self.assertEqual(app._slideshow_favorites_read_blocking(),
                         {"a.png", "c.png"})


class SlideshowStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "screensaver_state.json"
        self.patch = mock.patch.object(
            app, "_slideshow_state_file", lambda: (self.file, "host"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_write_from_the_tablet_keeps_the_keys_it_knows_nothing_about(self):
        # ram_circle_pos and cyberpunk are the desktop app's; the tablet has
        # no such furniture and must not reset them.
        self.file.write_text(json.dumps({
            "transition": "swirl",
            "ram_circle_pos": [40, 900],
            "cyberpunk": False,
        }), encoding="utf-8")
        state, source = app._slideshow_state_write_blocking(
            {"transition": "cube", "image_seconds": 20})
        self.assertEqual(source, "host")
        self.assertEqual(state["transition"], "cube")
        self.assertEqual(state["image_seconds"], 20)
        self.assertEqual(state["ram_circle_pos"], [40, 900])
        self.assertIs(state["cyberpunk"], False)

    def test_an_unreadable_state_file_is_an_empty_one_not_an_error(self):
        self.file.write_text("{ not json", encoding="utf-8")
        state, _ = app._slideshow_state_read_blocking()
        self.assertEqual(state, {})

    def test_where_the_settings_live_says_whose_they_are(self):
        # The real one: "host" only when ~/bin is actually mounted, because
        # the difference is invisible from the tablet and the operator asked
        # for the box's own setup.
        self.patch.stop()
        with mock.patch.object(app, "SLIDESHOW_HOST_BIN", Path("/nowhere")):
            path, source = app._slideshow_state_file()
            self.assertEqual(source, "station")
            self.assertNotIn("host-bin", str(path))
        self.patch.start()


class SlideshowShuffleTests(unittest.TestCase):
    """The deal must not change between pages of the same playlist."""

    def test_one_seed_gives_one_order_however_it_is_paged(self):
        import random
        rows = [{"file": f"{n}.png"} for n in range(200)]
        first = list(rows)
        random.Random(7).shuffle(first)
        second = list(rows)
        random.Random(7).shuffle(second)
        self.assertEqual([r["file"] for r in first],
                         [r["file"] for r in second])
        # And a different seed is a different deal, or every tablet in the
        # house would show the same picture at the same moment.
        third = list(rows)
        random.Random(8).shuffle(third)
        self.assertNotEqual([r["file"] for r in first],
                            [r["file"] for r in third])


if __name__ == "__main__":
    unittest.main()
