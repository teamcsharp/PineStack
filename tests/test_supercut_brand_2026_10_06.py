"""[supercut-brand] Wave F, 2026-10-06: the SUPERCUT brand card - three cinematically kerned rows in a font
System 3 rolls off the operator's collection, arriving and leaving with one of ten text animations System 3
rolls too - on every supercut.

1. supercut_brand.py alone: the three lines; the shelf (one level deep, non-fonts ignored, nothing when the
   collection is away); the roll through a fake die (and the seeded draw without one); the cache that copies
   once; the card's geometry with Pillow's bundled face and, when one is within reach, a real TrueType face;
   the fallback record; every effect's entry and exit (lengths, empty first frame, the finished card last, the
   exit from the card to nothing, characters moving independently, the same seed the same frames); the timing
   of a short, a shortened and a roomy clip; the three-overlay ffmpeg graph with its offsets (fake runner).
2. The station half, over fakes: the caption's three rows, the fonts setting, the shelf gated by the probe,
   the pineEX road's three rolls (noted on the hour's rolodex, cached, kept on the row), the hourly road's
   brand from the host and the plan that remembers it, the mux pass of the SFX guy's video road, the archive
   row that keeps the brand; and the patch tool reading this tree as applied.
3. In the container (imageio's ffmpeg 7.0.2 and Pillow): one real 3 s cut with the three overlays, the card
   absent at the start, on in the hold, gone at the end.

app.py is the first one on sys.path (PYTHONPATH=<stage>:<stage>/tests:/app runs this against a staged copy).
A real TrueType face for the card test comes from SUPERCUT_BRAND_TTF, else the station's font cache, else a
Windows font folder; without one that case is skipped.
"""
import asyncio
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from typing import Any
from unittest import mock

import supercut_brand as sb

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
LONG = "Chicken Tendo Little Pine Box FM Station"


def _pillow() -> bool:
    try:
        return importlib.import_module("PIL.Image") is not None
    except Exception:  # noqa: BLE001
        return False


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""


def _ttf() -> str:
    """A real TrueType face within reach, else ''."""
    named = os.environ.get("SUPERCUT_BRAND_TTF", "")
    if named and Path(named).is_file():
        return named
    for folder in (Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data")) / "fonts_cache", Path("C:/Windows/Fonts")):
        try:
            if folder.is_dir():
                for cand in sorted(folder.iterdir()):
                    if cand.suffix.lower() == ".ttf" and cand.name.lower() in ("arial.ttf", "verdana.ttf", "tahoma.ttf") or (
                            folder.name == "fonts_cache" and cand.suffix.lower() in sb.FONT_TYPES):
                        return str(cand)
        except OSError:
            continue
    return ""


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _diff(a: Any, b: Any) -> float:
    from PIL import ImageChops
    data = ImageChops.difference(a, b).convert("L").getdata()
    return sum(data) / max(1, len(data))


def _box(img: Any, g: Any) -> Any:
    return img.crop((g.x, g.y, g.x + g.tile.width, g.y + g.tile.height)).getbbox()


# ==================================================================================================
# 1. the module
class TheWords(unittest.TestCase):
    def test_three_rows_supercut_the_short_brand_the_long_name(self):
        self.assertEqual(sb.lines(LONG), ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual(sb.lines("  Pine   Box  "), ["SUPERCUT", "PINEBOX FM", "Pine Box"], "whitespace folded")
        self.assertEqual(sb.lines("")[2], "Pine Box FM", "no setting: the station's name")
        self.assertEqual(len(sb.lines("x" * 200)[2]), 80, "a long name is cut")
        self.assertTrue(all(ord(c) < 128 for c in Path(sb.__file__).read_text(encoding="utf-8")), "the module is ASCII")


class TheShelf(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fonts = self.tmp / "Fonts"
        for rel in ("akzidenz-grotesk-light.ttf", "Amazone.otf", "BankGothic/BankGothic.ttf", "BankGothic/readme.html",
                    "notes.md", "Deep/Deeper/too-deep.ttf", "Hitmarker/Hitmarker.TTF"):
            p = self.fonts / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"font " + rel.encode())

    def test_one_level_deep_fonts_only_sorted(self):
        got = [str(p.relative_to(self.fonts)).replace(os.sep, "/") for p in sb.font_shelf(self.fonts)]
        self.assertEqual(got, ["akzidenz-grotesk-light.ttf", "Amazone.otf", "BankGothic/BankGothic.ttf", "Hitmarker/Hitmarker.TTF"],
                         "sorted case-insensitively, the same order the dice labels use")

    def test_nothing_when_the_collection_is_away_or_the_folder_is_not_there(self):
        self.assertEqual(sb.font_shelf(self.fonts, reachable=False), [])
        self.assertEqual(sb.font_shelf(self.tmp / "nope"), [])
        self.assertEqual(sb.font_shelf(""), [])
        self.assertEqual(len(sb.font_shelf(self.fonts, most=2)), 2)

    def test_labels_are_the_stems_with_the_folder_when_two_collide(self):
        (self.fonts / "Other").mkdir()
        (self.fonts / "Other" / "BankGothic.ttf").write_bytes(b"x")
        shelf = sb.font_shelf(self.fonts)
        labels = sb.font_labels(shelf)
        self.assertEqual(len(labels), len(set(labels)), "unique")
        self.assertIn("BankGothic/BankGothic", labels)
        self.assertIn("Other/BankGothic", labels)
        self.assertIn("Amazone", labels)


class TheRoll(unittest.TestCase):
    def setUp(self):
        self.shelf = [Path("/f/Amazone.otf"), Path("/f/BankGothic/BankGothic.ttf"), Path("/f/zed.ttf")]

    def test_the_die_names_the_font_and_the_note_hears_it(self):
        heard = []
        asked = []

        def die(labels):
            asked.append(list(labels))
            return "BankGothic"
        got = sb.roll_font(self.shelf, die, lambda labels, picked: heard.append((labels, picked)))
        self.assertEqual(got, Path("/f/BankGothic/BankGothic.ttf"))
        self.assertEqual(asked, [["Amazone", "BankGothic", "zed"]])
        self.assertEqual(heard, [(["Amazone", "BankGothic", "zed"], "BankGothic")])
        self.assertEqual(sb.roll_font(self.shelf, lambda labels: 2), Path("/f/zed.ttf"), "an index does too")

    def test_no_die_or_a_broken_one_is_a_seeded_draw_and_an_empty_shelf_is_none(self):
        a = sb.roll_font(self.shelf, None, seed=4)
        self.assertEqual(a, sb.roll_font(self.shelf, None, seed=4), "the same seed, the same font")
        self.assertIn(a, self.shelf)
        self.assertEqual(sb.roll_font(self.shelf, lambda labels: "nope", seed=4), a, "a pick off the shelf: the seeded draw")

        def broken(labels):
            raise RuntimeError("no dice")
        self.assertEqual(sb.roll_font(self.shelf, broken, seed=4), a)
        self.assertIsNone(sb.roll_font([], lambda labels: "x"))

    def test_the_entry_and_the_exit_are_two_rolls_over_the_ten_effects(self):
        calls = []
        heard = []

        def die(key, options, label):
            calls.append((key, list(options), label))
            return {"supercut.text_in": "drop_bounce", "supercut.text_out": "wipe"}[key]
        got = sb.roll_effects(die, lambda key, options, picked: heard.append((key, picked)))
        self.assertEqual(got, ("drop_bounce", "wipe"))
        self.assertEqual([c[0] for c in calls], ["supercut.text_in", "supercut.text_out"])
        self.assertEqual(calls[0][1], list(sb.EFFECTS))
        self.assertIn("entry", calls[0][2])
        self.assertIn("exit", calls[1][2])
        self.assertEqual(heard, [("supercut.text_in", "drop_bounce"), ("supercut.text_out", "wipe")])
        self.assertEqual(len(sb.EFFECTS), 10)
        self.assertEqual(set(sb.EFFECT_SAY), set(sb.EFFECTS))
        self.assertEqual(set(sb.EXIT_SAY), set(sb.EFFECTS))
        self.assertEqual(set(sb.EXIT_SECONDS), set(sb.EFFECTS))

    def test_without_a_die_the_seed_decides(self):
        a = sb.roll_effects(None, seed=11)
        self.assertEqual(a, sb.roll_effects(None, seed=11))
        self.assertTrue(all(e in sb.EFFECTS for e in a))
        self.assertEqual(sb.roll_effects(lambda k, o, l: "nope", seed=11), a, "a name off the table: the seeded draw")
        self.assertEqual(sb.seed_for("sc-abc"), sb.seed_for("sc-abc"))
        self.assertNotEqual(sb.seed_for("sc-abc"), sb.seed_for("sc-abd"))


class TheCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = self.tmp / "share" / "Bank Gothic: Bold!.TTF"
        self.source.parent.mkdir()
        self.source.write_bytes(b"\x00\x01font")

    def test_copied_once_by_stem_and_suffix_the_cached_path_is_what_the_burn_reads(self):
        cache = self.tmp / "data" / "fonts_cache"
        got = sb.cache_font(self.source, cache)
        self.assertEqual(got, cache / "Bank Gothic- Bold.ttf")   # safe_stem: the colon and the bang become dashes
        self.assertEqual(got.read_bytes(), self.source.read_bytes())
        stamp = got.stat().st_mtime_ns
        time.sleep(0.02)
        self.assertEqual(sb.cache_font(self.source, cache), got)
        self.assertEqual(got.stat().st_mtime_ns, stamp, "the second ask copies nothing")
        self.source.write_bytes(b"\x00\x01font-v2!")
        sb.cache_font(self.source, cache)
        self.assertEqual(got.read_bytes(), b"\x00\x01font-v2!", "a source of another size is copied again")
        self.assertEqual(sorted(p.name for p in cache.iterdir()), ["Bank Gothic- Bold.ttf"], "no temporaries left")


@unittest.skipUnless(_pillow(), "Pillow")
class TheCard(unittest.TestCase):
    def test_geometry_with_the_bundled_face(self):
        lay = sb.layout(sb.rows(sb.lines(LONG), 640), None, 640, 360)
        self.assertTrue(lay.fell_back)
        self.assertEqual(lay.width, 640)
        self.assertEqual([r["text"] for r in lay.rows], ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual([r["size"] for r in lay.rows], [58, 25, 19], "width/11, width/26, width/34")
        self.assertEqual([r["tracking"] for r in lay.rows], [0.42, 0.38, 0.12])
        for r in lay.rows:
            self.assertLessEqual(r["width"], 640 - 2 * 32, r["text"])
            self.assertLess(abs((r["x0"] + r["x1"]) - 640), 3, "centred: " + r["text"])
        self.assertLess(lay.rows[0]["top"], lay.rows[1]["top"])
        self.assertLess(lay.rows[1]["top"], lay.rows[2]["top"])
        self.assertLessEqual(lay.height, 180, "never taller than half the picture")
        self.assertEqual(len(lay.glyphs), len("SUPERCUT") + len("PINEBOXFM") + len(LONG.replace(" ", "")))
        self.assertGreater(lay.rows[0]["size"], 2.2 * lay.rows[2]["size"], "row 1 about 2.3x row 3")
        gap = lay.rows[2]["top"] - (lay.rows[1]["top"] + lay.rows[1]["height"])
        self.assertAlmostEqual(gap, 0.35 * 19, delta=1.5, msg="rows 0.35 of row 3's size apart")
        img = sb.card(sb.lines(LONG), None, 640, 360)
        self.assertEqual(img.size, (640, lay.height))
        self.assertTrue(img.info["fell_back"])
        pixels = list(img.getdata())
        self.assertTrue(any(p[0] >= 215 and p[1] >= 215 and p[3] > 200 for p in pixels), "light grey ink")
        self.assertTrue(any(p[0] < 40 and 60 < p[3] < 200 for p in pixels), "a soft dark shadow")
        self.assertFalse(any(p[3] > 0 for p in pixels[:640]), "no box: the top row of pixels is clear")

    def test_a_long_row_is_shrunk_to_fit_and_a_small_picture_keeps_the_proportions(self):
        lay = sb.layout(sb.rows(["SUPERCUT", "PINEBOX FM", "x" * 120], 320), None, 320, 180)
        self.assertLess(lay.rows[2]["size"], 9, "shrunk under width/34")
        self.assertLessEqual(lay.rows[2]["width"], 320 - 2 * 16)
        self.assertLessEqual(lay.height, 90)
        small = sb.layout(sb.rows(sb.lines(LONG), 320), None, 320, 180)
        self.assertEqual([r["size"] for r in small.rows], [29, 12, 9])
        self.assertEqual(small.width, 320)
        wide = sb.layout(sb.rows(sb.lines(LONG), 1280), None, 1280, 720)
        self.assertEqual(wide.rows[0]["size"], 116)
        self.assertLessEqual(wide.height, 360)

    def test_a_missing_font_falls_back_and_says_why(self):
        lay = sb.layout(sb.rows(sb.lines(LONG), 640), "/nowhere/at/all.ttf", 640, 360)
        self.assertTrue(lay.fell_back)
        self.assertTrue(lay.why.startswith("OSError"), lay.why)
        rec = sb.brand_record("/nowhere/at/all.ttf", "", True, lay.why)
        self.assertEqual((rec["font"], rec["rolled_font"], rec["fell_back"]), (sb.DEFAULT_FACE, "all", True))
        self.assertTrue(rec["why"].startswith("OSError"))
        none = sb.brand_record(None, "", True)
        self.assertEqual((none["font"], none["font_file"], none["cached"], none["why"]), (sb.DEFAULT_FACE, "", "", "no font on the shelf"))
        fine = sb.brand_record("/f/BankGothic.ttf", "/cache/BankGothic.ttf", False, lines=["a"])
        self.assertEqual((fine["font"], fine["font_file"], fine["cached"], fine["fell_back"], fine["why"], fine["lines"]),
                         ("BankGothic", str(Path("/f/BankGothic.ttf")), "/cache/BankGothic.ttf", False, "", ["a"]))

    @unittest.skipUnless(_ttf(), "a real TrueType face within reach")
    def test_a_real_face_is_set_without_falling_back(self):
        lay = sb.layout(sb.rows(sb.lines(LONG), 640), _ttf(), 640, 360)
        self.assertFalse(lay.fell_back, lay.why)
        self.assertEqual(lay.why, "")
        for r in lay.rows:
            self.assertLessEqual(r["width"], 640 - 64)
        img = sb.card(sb.lines(LONG), _ttf(), 640, 360)
        self.assertFalse(img.info["fell_back"])
        self.assertIsNotNone(img.getbbox())


@unittest.skipUnless(_pillow(), "Pillow")
class TheEffects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lay = sb.layout(sb.rows(sb.lines(LONG), 640), None, 640, 360)
        cls.hold = sb.compose(cls.lay)

    def test_every_entry_starts_empty_and_ends_on_the_card_every_exit_leaves_from_it(self):
        for effect in sb.EFFECTS:
            ins = sb.entry_frames(self.lay, effect, seed=7)
            outs = sb.exit_frames(self.lay, effect, seed=7)
            self.assertEqual(len(ins), max(2, round(sb.entry_seconds(effect, self.lay) * 24)), effect)
            self.assertEqual(len(outs), max(2, round(sb.exit_seconds(effect) * 24)), effect)
            self.assertTrue(1.0 <= len(ins) / 24 <= 2.5 or effect == "pop", "%s: %d frames" % (effect, len(ins)))
            self.assertTrue(0.5 <= len(outs) / 24 <= 1.2, effect)
            self.assertIsNone(ins[0].getbbox(), effect + ": the first entry frame is empty or off-screen")
            self.assertLess(_diff(ins[-1], self.hold), 0.5, effect + ": the last entry frame is the card")
            self.assertLess(_diff(outs[0], self.hold), 0.5, effect + ": the first exit frame is the card")
            self.assertIsNone(outs[-1].getbbox(), effect + ": the last exit frame is empty")
            self.assertEqual(ins[0].size, self.hold.size)

    def test_per_character_effects_move_characters_independently(self):
        first, last = self.lay.glyphs[0], self.lay.glyphs[-1]
        for effect in ("flip_chars", "typewriter", "scatter"):
            ins = sb.entry_frames(self.lay, effect, seed=7)
            mid = ins[len(ins) // 3]
            self.assertNotEqual(_box(mid, first), _box(mid, last), effect + ": the first and the last character differ")
            self.assertIsNotNone(_box(mid, first) if effect != "scatter" else True, effect)

    def test_row_effects_stagger_the_rows(self):
        # drop and pop start the top row first; a rise starts every row at the bottom edge, so the
        # lower row reaches the picture first - the lead row is the one nearest where it starts
        for effect, lead, follow in (("drop_bounce", 0, 2), ("pop", 0, 2), ("rise_settle", 2, 0)):
            ins = sb.entry_frames(self.lay, effect, seed=7)
            early = ins[max(1, len(ins) // 6)]
            lead_seen = any(_box(early, g) for g in self.lay.row_glyphs(lead))
            follow_seen = any(_box(early, g) for g in self.lay.row_glyphs(follow))
            self.assertTrue(lead_seen or not follow_seen, effect + ": the lead row is never behind the last row")

    def test_the_same_seed_gives_the_same_frames(self):
        a = sb.entry_frames(self.lay, "scatter", seed=5)
        b = sb.entry_frames(self.lay, "scatter", seed=5)
        c = sb.entry_frames(self.lay, "scatter", seed=6)
        k = len(a) // 2
        self.assertEqual(_diff(a[k], b[k]), 0.0)
        self.assertGreater(_diff(a[k], c[k]), 0.0)
        g = sb.entry_frames(self.lay, "glitch", seed=5)
        self.assertEqual(_diff(g[3], sb.entry_frames(self.lay, "glitch", seed=5)[3]), 0.0)


@unittest.skipUnless(_pillow(), "Pillow")
class TheTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lay = sb.layout(sb.rows(sb.lines(LONG), 640), None, 640, 360)

    def test_a_clip_under_two_seconds_wears_the_card_from_its_first_frame(self):
        tm = sb.timing(1.0, "slow_reveal", "scatter", self.lay)
        self.assertEqual((tm["shortened"], tm["entry"], tm["exit"], tm["hold"]), ("hold-only", None, None, [0.0, 1.0]))
        self.assertEqual(sb.timing(0, "pop", "pop", self.lay)["hold"], [0.0, 3600.0], "an unknown length: on until the end")

    def test_little_room_shortens_the_hold_then_takes_the_short_pair_then_the_card_alone(self):
        roomy = sb.timing(10.0, "slow_reveal", "scatter", self.lay)
        self.assertEqual(roomy["shortened"], "")
        self.assertEqual(roomy["entry"], [0.4, 2.9])
        self.assertEqual(roomy["exit"][1], 9.7, "the exit ends 0.3 s before the end")
        self.assertEqual(roomy["hold"], [2.9, 8.6])
        short_hold = sb.timing(6.0, "slow_reveal", "scatter", self.lay)
        self.assertEqual(short_hold["shortened"], "hold")
        self.assertEqual((short_hold["effect_in"], short_hold["effect_out"]), ("slow_reveal", "scatter"))
        pair = sb.timing(4.0, "slow_reveal", "scatter", self.lay)
        self.assertEqual((pair["shortened"], pair["effect_in"], pair["effect_out"]), ("short-effects", "pop", "slow_reveal"))
        self.assertEqual(pair["exit_seconds"], 0.5)
        self.assertEqual(pair["exit"][1], 3.7)
        alone = sb.timing(2.5, "pop", "pop", self.lay)
        self.assertEqual((alone["shortened"], alone["hold"]), ("hold-only", [0.4, 2.2]))


@unittest.skipUnless(_pillow(), "Pillow")
class TheGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_three_overlays_offset_to_their_windows_ten_px_up(self):
        prep = sb.prepare(sb.lines(LONG), None, 640, 360, 10.0, "drop_bounce", "wipe", self.tmp / "brand", seed=3)
        self.assertEqual(prep["frames"], {"entry": 31, "hold": 1, "exit": 22})
        self.assertEqual(len(list((self.tmp / "brand").glob("in_*.png"))), 31)
        self.assertEqual(len(list((self.tmp / "brand").glob("out_*.png"))), 22)
        self.assertTrue((self.tmp / "brand" / "hold.png").is_file())
        self.assertEqual(prep["card"][0], 640)
        inputs, graph = sb.overlay_graph(prep)
        self.assertEqual(inputs[:7], ["-itsoffset", "0.400", "-framerate", "24", "-start_number", "0", "-i"])
        self.assertTrue(inputs[7].endswith("in_%04d.png"))
        self.assertEqual(inputs[8:16], ["-itsoffset", "1.700", "-loop", "1", "-framerate", "24", "-t", "7.100"])
        self.assertTrue(inputs[17].endswith("hold.png"))
        self.assertEqual(inputs[18:20], ["-itsoffset", "8.800"])
        self.assertEqual(graph.count("overlay="), 3)
        self.assertIn("[0:v:0][1:v]overlay=x=(W-w)/2:y=H-h-10:eof_action=pass:enable='between(t,0.400,1.700)'[v1]", graph)
        self.assertIn("[v1][2:v]overlay=x=(W-w)/2:y=H-h-10:eof_action=pass:enable='between(t,1.700,8.800)'[v2]", graph)
        self.assertTrue(graph.endswith("enable='between(t,8.800,9.700)',format=yuv420p[v]"), graph)
        inputs2, graph2 = sb.overlay_graph(prep, first_input=2)
        self.assertIn("[0:v:0][2:v]overlay", graph2)
        self.assertIn("[v3][4:v]overlay", graph2)

    def test_a_short_clip_is_the_hold_alone_and_the_burn_runs_one_pass(self):
        prep = sb.prepare(sb.lines(LONG), None, 320, 180, 1.0, "scatter", "glitch", self.tmp / "brand", seed=1)
        self.assertEqual(prep["frames"], {"entry": 0, "hold": 1, "exit": 0})
        inputs, graph = sb.overlay_graph(prep)
        self.assertEqual(graph.count("overlay="), 1)
        self.assertEqual(inputs[:4], ["-itsoffset", "0.000", "-loop", "1"])
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw))
            Path(cmd[-1]).write_bytes(b"mp4")
            return mock.Mock(returncode=0)
        src = self.tmp / "src.mp4"
        src.write_bytes(b"src")
        got = sb.burn("ffmpeg", src, self.tmp / "out" / "cut.mp4", prep, run=run, timeout=33)
        self.assertTrue((self.tmp / "out" / "cut.mp4").is_file())
        self.assertFalse((self.tmp / "out" / "cut.tmp.mp4").exists())
        cmd, kw = calls[0]
        self.assertEqual(cmd[:7], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i"])
        self.assertEqual(cmd[7], str(src))
        self.assertIn("-filter_complex", cmd)
        self.assertEqual(cmd[cmd.index("-map") + 1], "[v]")
        self.assertIn("0:a?", cmd)
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
        self.assertEqual(kw["timeout"], 33)
        self.assertTrue(cmd[-1].endswith("cut.tmp.mp4"))
        self.assertEqual(got["path"], str(self.tmp / "out" / "cut.mp4"))
        copy = sb.burn_command("ffmpeg", src, "x.mp4", prep, audio="copy")
        self.assertEqual(copy[copy.index("-c:a") + 1], "copy")
        rec = sb.record_of(prep, None, "", sb.lines(LONG), "scatter", "glitch", rolled=False)
        self.assertEqual((rec["font"], rec["effect_in"], rec["effect_in_used"], rec["rolled"]), (sb.DEFAULT_FACE, "scatter", "", False))
        self.assertEqual(rec["timing"]["shortened"], "hold-only")
        self.assertEqual(rec["lines"][2], LONG)
        sb.clean_workdir(self.tmp / "brand")
        self.assertFalse((self.tmp / "brand").exists())


# ==================================================================================================
# 2. the station half
try:
    import test_pineex_supercut_2026_10_06 as pine
except Exception:  # noqa: BLE001 - no app.py on sys.path: the station half is skipped
    pine = None


def _fonts(root: Path, names=("A.ttf", "B.ttf")) -> Path:
    folder = root / "Fonts"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"font " + name.encode())
    return folder


@unittest.skipUnless(pine is not None, "app.py on sys.path")
class TheCaptionAndTheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = pine.supercut_ns(self.tmp)

    def test_the_caption_is_the_three_rows_with_the_station_setting_s_long_name(self):
        caption = self.ns["h3_supercut_caption"]
        self.assertEqual(caption(pine.pineex_row()), ["SUPERCUT", "PINEBOX FM", "Pine Box FM"])
        self.ns["dj_settings"] = lambda: {"station_name": LONG}
        self.assertEqual(caption(pine.pineex_row()), ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual(self.ns["h3_supercut_station"](), LONG)
        self.ns["dj_settings"] = lambda: (_ for _ in ()).throw(RuntimeError("no settings"))
        self.assertEqual(caption({}), ["SUPERCUT", "PINEBOX FM", "Pine Box FM"], "a broken setting never costs the card")

    def test_the_fonts_folder_setting_has_a_default_and_takes_an_absolute_path(self):
        self.assertIn('"supercut_fonts_folder": "Fonts",', pine.APP_TEXT, "DEFAULT_DJ")
        self.assertIn('"supercut_fonts_folder": (str(raw_dj.get("supercut_fonts_folder")', pine.APP_TEXT, "kept on every save")
        folder = self.ns["supercut_fonts_folder"]
        self.ns["SFX_ROOT"] = self.tmp / "samples"
        self.ns["DEFAULT_DJ"] = {"supercut_fonts_folder": "Fonts"}
        self.assertEqual(folder(), self.tmp / "samples" / "Fonts", "the default, under SFX_ROOT")
        self.ns["dj_settings"] = lambda: {"supercut_fonts_folder": "moved/Fonts"}
        self.assertEqual(folder(), self.tmp / "samples" / "moved" / "Fonts")
        absolute = str(self.tmp / "newnas" / "Fonts")
        self.ns["dj_settings"] = lambda: {"supercut_fonts_folder": absolute}
        self.assertEqual(folder(), Path(absolute), "an absolute path is the folder itself")
        self.ns["dj_settings"] = lambda: {}
        self.assertEqual(folder(), self.tmp / "samples" / "Fonts")

    def test_the_shelf_is_listed_only_while_the_collection_answers(self):
        shelf = self.ns["supercut_font_shelf"]
        self.ns["SFX_ROOT"] = self.tmp / "samples"
        self.ns["DEFAULT_DJ"] = {"supercut_fonts_folder": "Fonts"}
        _fonts(self.tmp / "samples")
        self.assertEqual(shelf(), [], "no probe at all: nothing is listed")
        self.ns["sfx_reachable"] = lambda: True
        self.ns["sfx_reach_under"] = lambda p: True
        self.assertEqual([p.name for p in shelf()], ["A.ttf", "B.ttf"])
        self.ns["sfx_reachable"] = lambda: False
        self.assertEqual(shelf(), [], "the collection away: nothing is listed, nothing is stat-ed")
        elsewhere = _fonts(self.tmp / "newnas", ("C.otf",))
        self.ns["dj_settings"] = lambda: {"supercut_fonts_folder": str(elsewhere)}
        self.ns["sfx_reach_under"] = lambda p: False
        self.assertEqual([p.name for p in shelf()], ["C.otf"], "an absolute folder off the collection is not gated")


@unittest.skipUnless(pine is not None, "app.py on sys.path")
class ThePineexRoad(unittest.TestCase):
    """The supercut version of an hourly render rolls its font and its two effects, notes them on the hour's
    rolodex, caches the font, burns with it and keeps the brand on the gallery row."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = pine.supercut_ns(self.tmp)
        self.ads = self.tmp / "comfy" / "sfx_ads"
        self.ads.mkdir(parents=True)
        self.burns = []
        self.rolls = []
        self.committed = []
        self.hour = {"hour": "h3h-1", "goal": "g", "at": time.time(), "rolls": {"host": {"key": "h3.hourly_host", "picked": "x"}}}
        ns = self.ns

        def fake_burn(source, target, lines, exe="", brand=None):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            self.burns.append((Path(source), Path(target), list(lines), brand))
            return {"path": str(target), "size": [640, 360], "lines": list(lines)}

        def s3_choice(key, options, label="", tabled=True):
            self.rolls.append((key, list(options), label))
            return {"supercut.font": "B", "supercut.text_in": "drop_bounce", "supercut.text_out": "wipe"}[key]

        def slot_note(name, key, opts, picked):
            ns["_H3_HOURLY_ROLLS"][name] = {"key": key, "picked": picked, "opts": list(opts)[:40], "dice": 0.5}
        ns.update({
            "h3_supercut_burn": fake_burn, "s3_choice": s3_choice, "_h3_slot_note": slot_note, "_H3_HOURLY_ROLLS": {},
            "_H3_PROMPTS_HOURS": [self.hour], "h3_prompts_commit_hour": lambda entry: self.committed.append(entry),
            "_h3_prompts_offloop": lambda fn, *args: fn(*args),
            "SFX_ROOT": self.tmp / "samples_root", "DEFAULT_DJ": {"supercut_fonts_folder": "Fonts"},
            "dj_settings": lambda: {"station_name": LONG, "supercut_fonts_folder": "Fonts"},
            "data_path": lambda *parts: self.tmp / "data" / Path(*parts),
            "sfx_reachable": lambda: True, "sfx_reach_under": lambda p: True})
        _fonts(self.tmp / "samples_root")

    def land(self, row):
        for name in row["files"]:
            (self.ads / name).write_bytes(b"\x00" * 5000)
        self.ns["_gens"].write_text(json.dumps(row) + "\n", encoding="utf-8")
        return row

    def test_three_rolls_noted_on_the_hour_the_font_cached_the_row_keeps_the_brand(self):
        row = self.land(pine.pineex_row())
        made = asyncio.run(self.ns["h3_supercut_version"](row))
        self.assertIsNotNone(made)
        self.assertEqual([r[0] for r in self.rolls], ["supercut.font", "supercut.text_in", "supercut.text_out"])
        self.assertEqual(self.rolls[0][1], ["A", "B"], "the shelf's labels")
        self.assertEqual(self.rolls[0][2], sb.LABEL_FONT)
        self.assertEqual(self.rolls[1][1], list(sb.EFFECTS))
        # the burn got the plan: the cached copy, never the share
        source, target, lines, brand = self.burns[0]
        self.assertEqual(lines, ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual(brand["font_path"], str(self.tmp / "samples_root" / "Fonts" / "B.ttf"))
        self.assertEqual(brand["cached"], str(self.tmp / "data" / "fonts_cache" / "B.ttf"))
        self.assertTrue(Path(brand["cached"]).is_file())
        self.assertEqual((brand["effect_in"], brand["effect_out"], brand["rolled"], brand["shelf"], brand["station"]),
                         ("drop_bounce", "wipe", True, 2, LONG))
        self.assertEqual(brand["seed"], sb.seed_for("pid-1"))
        # the row keeps font and brand
        self.assertEqual((made["font"], made["brand"]["effect_in"], made["brand"]["effect_out"]), ("B", "drop_bounce", "wipe"))
        rec = self.ns["_read_all_generations"]()[0]
        self.assertEqual(rec["supercut_version"]["font"], "B")
        self.assertEqual(rec["supercut_version"]["brand"]["seed"], sb.seed_for("pid-1"))
        # the hour's rolodex entry carries the three rolls, committed; the live tray is left clean
        self.assertEqual(set(self.hour["rolls"]), {"host", "supercut_font", "supercut_text_in", "supercut_text_out"})
        self.assertEqual(self.hour["rolls"]["supercut_font"]["picked"], "B")
        self.assertEqual(self.hour["rolls"]["supercut_font"]["opts"], ["A", "B"])
        self.assertEqual(self.hour["rolls"]["supercut_text_in"]["key"], "supercut.text_in")
        self.assertEqual(len(self.committed), 3)
        self.assertEqual(self.committed[-1]["hour"], "h3h-1")
        self.assertEqual(self.ns["_H3_HOURLY_ROLLS"], {})
        self.assertTrue(any("set in B, drop_bounce in / wipe out" in l for l in self.ns["_logs"]), self.ns["_logs"])

    def test_the_collection_away_the_card_is_set_in_the_bundled_face_and_says_so(self):
        self.ns["sfx_reachable"] = lambda: False
        row = self.land(pine.pineex_row())
        made = asyncio.run(self.ns["h3_supercut_version"](row))
        self.assertEqual([r[0] for r in self.rolls], ["supercut.text_in", "supercut.text_out"], "no shelf: the font is not rolled")
        brand = self.burns[0][3]
        self.assertEqual((brand["font_path"], brand["cached"], brand["shelf"]), ("", "", 0))
        self.assertEqual(made["font"], sb.DEFAULT_FACE)
        self.assertNotIn("supercut_font", self.hour["rolls"])
        self.assertIn("supercut_text_in", self.hour["rolls"])

    def test_the_burn_s_own_record_is_what_the_row_keeps(self):
        record = {"font": "B", "fell_back": False, "effect_in": "drop_bounce", "effect_out": "wipe", "effect_in_used": "pop",
                  "effect_out_used": "slow_reveal", "seed": 1, "frames": {"entry": 20, "hold": 1, "exit": 12}}

        def burn(source, target, lines, exe="", brand=None):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            return {"path": str(target), "size": [640, 360], "lines": list(lines), "brand": record}
        self.ns["h3_supercut_burn"] = burn
        made = asyncio.run(self.ns["h3_supercut_version"](self.land(pine.pineex_row())))
        self.assertEqual(made["brand"], record)
        self.assertEqual(made["font"], "B")
        self.assertTrue(any("set in B, pop in / slow_reveal out" in l for l in self.ns["_logs"]), "the log says what was used")

    def test_a_roll_without_the_hour_in_memory_still_burns(self):
        self.ns["_H3_PROMPTS_HOURS"] = []
        made = asyncio.run(self.ns["h3_supercut_version"](self.land(pine.pineex_row())))
        self.assertEqual(made["font"], "B")
        self.assertEqual(self.committed, [])
        self.assertEqual(self.ns["_H3_HOURLY_ROLLS"], {}, "the tray is still left clean")


class TheHourlyRoad(unittest.TestCase):
    """The SFX guy's render(): the brand comes from the host's supercut_brand_plan (app.py's globals), rides
    into render_video, and the plan the archive keeps remembers it."""

    def setUp(self):
        import sfx_supercut as cut
        self.cut = cut
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.asked = []
        self.brand = {"font_path": "/share/Fonts/B.ttf", "cached": str(self.tmp / "fonts_cache" / "B.ttf"),
                      "effect_in": "pop", "effect_out": "wipe", "seed": 5, "rolled": True, "shelf": 2, "station": LONG}

        async def brand_plan(seed_text, note=None):
            self.asked.append(seed_text)
            return dict(self.brand)
        self.host = {"DATA_DIR": self.tmp, "VOICE_MEDIA_DIR": self.tmp, "supercut_brand_plan": brand_plan}
        clips = [{"sid": "s%d" % i, "path": "/clips/%d.mp4" % i, "said": "Pine Box FM", "seconds": 3, "from_s": 0, "until_s": 3}
                 for i in range(3)]
        self.plan = {"id": "sc-" + "b" * 24, "ok": True, "complete": True, "source_only": True, "seconds": 9,
                     "config": cut.config({"station": "Pine Box FM"}), "clips": clips, "cues": [], "occurrence": "hour-1"}

    def render(self, host):
        runtime = self.cut.SupercutRuntime(host)
        self.addCleanup(runtime.source_pool.shutdown, wait=False)
        self.addCleanup(runtime.catalog_pool.shutdown, wait=False)
        got = []
        rendered = {"ok": True, "complete": True, "source_only": True, "seconds": 9.0, "path": str(self.tmp / "a.wav"),
                    "cues": [], "recorded_text": "x", "source_plan": dict(self.plan)}

        def fake_video(plan, result, output, executable, **kw):
            got.append(kw)
            return {"kind": "video", "video": "a.mp4", "video_path": str(output), "video_sha256": "deadbeef",
                    "video_source_only": True, "video_seconds": 9.0, "video_size": [640, 360], "video_codec": "h264",
                    "video_bytes": 1, "brand": sb.brand_record(kw.get("brand", {}).get("font_path") if kw.get("brand") else None,
                                                                 (kw.get("brand") or {}).get("cached"), not kw.get("brand"),
                                                                 lines=sb.lines(kw.get("station")))}
        runtime.archive.record = lambda result: {"id": "sca-" + "c" * 24, "brand": result["source_plan"].get("brand")}
        with mock.patch.object(self.cut, "render_source_plan", return_value=rendered), \
                mock.patch("sfx_supercut_video.render_video", fake_video):
            result = asyncio.run(runtime.render(self.plan))
        return runtime, result, got

    def test_the_brand_from_the_host_rides_into_the_video_and_the_plan_remembers_it(self):
        runtime, result, got = self.render(self.host)
        self.assertEqual(self.asked, [self.plan["id"]], "seeded by the plan's id")
        self.assertEqual(got[0]["brand"], self.brand)
        self.assertEqual(got[0]["station"], LONG, "the station's long name from the plan")
        self.assertEqual(result["brand"]["font"], "B")
        self.assertEqual(result["brand"]["lines"], ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual(result["source_plan"]["brand"]["font"], "B")
        self.assertEqual(result["archive"]["brand"]["font"], "B", "the archive was handed the plan with its brand")
        saved = runtime.load(self.plan["id"])
        self.assertEqual(saved["brand"]["font"], "B", "the plan on disk remembers the card")

    def test_without_the_host_hook_the_card_still_goes_on_in_the_bundled_face(self):
        host = dict(self.host)
        host.pop("supercut_brand_plan")
        runtime, result, got = self.render(host)
        self.assertIsNone(got[0]["brand"])
        self.assertEqual(got[0]["station"], "Pine Box FM", "the plan's own station")
        self.assertEqual(result["brand"]["font"], sb.DEFAULT_FACE)


@unittest.skipUnless(_pillow(), "Pillow")
class TheVideoRoad(unittest.TestCase):
    """render_video: the frames beside the cuts, three overlays in the mux pass, the brand in the result."""

    def setUp(self):
        import sfx_supercut_video as video
        self.video = video
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        clips = []
        for i in range(2):
            p = self.tmp / ("clip%d.mp4" % i)
            p.write_bytes(b"clip")
            clips.append({"sid": "s%d" % i, "path": str(p), "mtime": p.stat().st_mtime, "said": "x"})
        self.plan = {"id": "sc-" + "d" * 24, "clips": clips, "config": {"station": "Pine Box FM"}}
        self.result = {"path": str(self.tmp / "a.wav"), "seconds": 10.0,
                       "cues": [{"sid": "s0", "source_from": 0.0, "body_seconds": 5.0}, {"sid": "s1", "source_from": 1.0, "body_seconds": 5.0}]}
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(list(cmd))
            if cmd[-1].endswith(".mp4"):
                Path(cmd[-1]).write_bytes(b"mp4")
            return mock.Mock(returncode=0)
        self.run = run
        self.facts = {"video_sha256": "x", "video_bytes": 3, "video_seconds": 10.0, "video_size": [640, 360], "video_codec": "h264"}

    def test_the_mux_pass_carries_the_three_overlays_and_the_result_the_brand(self):
        brand = {"font_path": "", "cached": "", "effect_in": "pop", "effect_out": "wipe", "seed": 9, "rolled": True, "shelf": 0}
        with mock.patch.object(self.video.subprocess, "run", self.run), mock.patch.object(self.video, "video_facts", return_value=self.facts):
            got = self.video.render_video(self.plan, self.result, self.tmp / "out.mp4", "ffmpeg", brand=brand, station=LONG)
        self.assertEqual(len(self.calls), 4, "two cuts, the mux, the decode check")
        mux = self.calls[2]
        self.assertEqual(mux[6:9], ["-f", "concat", "-safe"])
        self.assertIn("-filter_complex", mux)
        graph = mux[mux.index("-filter_complex") + 1]
        self.assertEqual(graph.count("overlay="), 3)
        self.assertIn("[0:v:0][2:v]overlay=x=(W-w)/2:y=H-h-10", graph, "the overlays start at input 2 (0 the cuts, 1 the audio)")
        self.assertIn("[v3][4:v]overlay", graph)
        self.assertTrue(graph.endswith("format=yuv420p[v]"))
        self.assertEqual(mux[mux.index("-map") + 1], "[v]")
        self.assertIn("1:a:0", mux)
        self.assertEqual(mux[mux.index("-c:v") + 1], "libx264")
        self.assertEqual(mux.count("-itsoffset"), 3)
        self.assertEqual(mux[mux.index("-itsoffset") + 1], "0.400")
        self.assertIn("-t", mux)
        self.assertEqual((got["kind"], got["video"]), ("video", "out.mp4"))
        self.assertEqual(got["brand"]["font"], sb.DEFAULT_FACE)
        self.assertEqual(got["brand"]["lines"], ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual((got["brand"]["effect_in"], got["brand"]["effect_out"], got["brand"]["rolled"]), ("pop", "wipe", True))
        self.assertEqual(got["brand"]["frames"]["entry"], 20)
        self.assertEqual(got["brand"]["timing"]["exit"][1], 9.7)
        self.assertFalse(list(self.tmp.glob("pine-supercut-video-*")), "the frames went with the temporary folder")

    def test_without_a_brand_the_effects_are_seeded_by_the_plan_and_the_station_is_the_config_s(self):
        with mock.patch.object(self.video.subprocess, "run", self.run), mock.patch.object(self.video, "video_facts", return_value=self.facts):
            got = self.video.render_video(self.plan, self.result, self.tmp / "out.mp4", "ffmpeg")
        self.assertEqual(got["brand"]["rolled"], False)
        self.assertEqual((got["brand"]["effect_in"], got["brand"]["effect_out"]), sb.roll_effects(None, None, sb.seed_for(self.plan["id"])))
        self.assertEqual(got["brand"]["lines"][2], "Pine Box FM")


class TheArchive(unittest.TestCase):
    def setUp(self):
        import sfx_supercut as cut
        from sfx_supercut_archive import SupercutArchive
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.ads = self.tmp / "sfx_ads"
        self.host = {"DATA_DIR": self.tmp, "SFX_ADS_DIR": self.ads, "VOICE_MEDIA_DIR": self.media, "media_sign": lambda key: "s-" + key}
        self.archive = SupercutArchive(self.host)
        self.path = self.media / ("f" * 32 + ".wav")
        with wave.open(str(self.path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            out.writeframes(b"\x10\x00" * int(45 * 24000))
        said = ["Hello welcome"] + ["Listen to radio music number " + str(i) for i in range(13)] + ["Goodbye Pine Box FM"]
        clips = [{"sid": "sid-" + str(i), "path": "/original/" + str(i) + ".wav", "said": text, "seconds": 3, "from_s": 0, "until_s": 3,
                  "mtime": 123, "role": "opening" if i == 0 else "closing" if i == 14 else "sell"} for i, text in enumerate(said)]
        cues = [dict(p, at=i * 3, until=(i + 1) * 3, body_seconds=3, source_from=0, source_until=3) for i, p in enumerate(clips)]
        self.brand = sb.brand_record("/share/Fonts/BankGothic.ttf", "/data/fonts_cache/BankGothic.ttf", False,
                                     lines=sb.lines(LONG), effect_in="scatter", effect_out="glitch", seed=3)
        self.plan = {"id": "sc-" + "a" * 24, "ok": True, "complete": True, "source_only": True, "seconds": 45,
                     "config": cut.config({}), "clips": clips, "cues": cues, "rendered_at": 123, "clip": self.path.name,
                     "occurrence": "hour-1", "generated_script": "An authored pitch.", "brand": self.brand}
        self.result = {"ok": True, "complete": True, "source_only": True, "seconds": 45, "source_plan": self.plan,
                       "path": str(self.path), "cues": cues, "recorded_text": " / ".join(said)}

    def test_the_row_keeps_the_brand_and_every_view_shows_it(self):
        row = self.archive.record(self.result)
        self.assertEqual(row["brand"]["font"], "BankGothic")
        self.assertEqual(row["brand"]["lines"], ["SUPERCUT", "PINEBOX FM", LONG])
        self.assertEqual(self.archive.detail(row["id"])["brand"]["effect_in"], "scatter")
        listed = self.archive.list(summary=True)["rows"][0]
        self.assertEqual(listed["brand"]["font"], "BankGothic", "the studio's summary rows carry it")
        self.assertNotIn("source_plan", listed)
        kept = json.loads((self.ads / "supercuts" / (row["id"] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(kept["brand"]["cached"], "/data/fonts_cache/BankGothic.ttf")

    def test_an_older_row_surfaces_the_brand_its_plan_carries_and_a_row_without_one_has_none(self):
        old = {"metadata": json.dumps({"id": "sca-x", "source_plan": {"brand": {"font": "Amazone"}}}), "reusable_ad_id": ""}
        self.assertEqual(self.archive.decorate(old)["brand"], {"font": "Amazone"})
        bare = {"metadata": json.dumps({"id": "sca-y", "source_plan": {}}), "reusable_ad_id": ""}
        self.assertNotIn("brand", self.archive.decorate(bare))
        self.plan.pop("brand")
        row = self.archive.record(self.result)
        self.assertNotIn("brand", row)


@unittest.skipUnless(pine is not None, "app.py on sys.path")
class PatchApplied(unittest.TestCase):
    def test_every_edit_reads_applied_on_this_tree(self):
        mod = _tool("supercut_brand_patch")
        out = io.StringIO()
        held, sys.stdout = sys.stdout, out
        try:
            code = mod.main(["supercut_brand_patch.py", "--check", str(pine.APP_PY.parent)])
        finally:
            sys.stdout = held
        self.assertEqual(code, 2, "every edit should read applied on %s:\n%s" % (pine.APP_PY, out.getvalue()))
        self.assertTrue(all(ord(c) < 128 for c in (TOOLS / "supercut_brand_patch.py").read_text(encoding="utf-8")), "the tool is ASCII")
        self.assertTrue(all(ord(c) < 128 for c in pine.supercut_section()), "the section is ASCII")
        self.assertIn("import supercut_brand as _supercut_brand", pine.supercut_section())


# ==================================================================================================
# 3. one real cut in the container
@unittest.skipUnless(pine is not None and _ffmpeg() and _pillow(), "app.py, the container's imageio ffmpeg and Pillow")
class RealBurn(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = pine.supercut_ns(self.tmp)
        self.exe = _ffmpeg()
        self.source = self.tmp / "source.mp4"
        subprocess.run([self.exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                        "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        str(self.source)], check=True, capture_output=True, timeout=60)

    def frames(self, path, wanted):
        """The frames at the given indexes (24 fps) as (bytes, w, h), plus the meta."""
        import imageio_ffmpeg
        reader = imageio_ffmpeg.read_frames(str(path))
        meta = next(reader)
        out = {}
        try:
            for ix, raw in enumerate(reader):
                if ix in wanted:
                    out[ix] = bytes(raw)
                if ix >= max(wanted):
                    break
        finally:
            reader.close()
        w, h = meta["size"]
        return meta, out, w, h

    def test_the_card_is_absent_at_the_start_on_in_the_hold_and_gone_at_the_end(self):
        target = self.tmp / "samples" / "pineEX" / "out-supercut.mp4"
        began = time.monotonic()
        got = self.ns["h3_supercut_burn"](self.source, target, sb.lines(LONG), self.exe,
                                          {"effect_in": "slow_reveal", "effect_out": "scatter", "seed": 1, "rolled": True})
        took = time.monotonic() - began
        self.assertTrue(target.is_file())
        self.assertFalse(target.with_name("out-supercut.brand").exists(), "the frames folder is gone")
        self.assertFalse(target.with_name("out-supercut.tmp.mp4").exists())
        brand = got["brand"]
        self.assertEqual((brand["effect_in"], brand["effect_out"]), ("slow_reveal", "scatter"), "as rolled")
        self.assertEqual((brand["effect_in_used"], brand["effect_out_used"]), ("pop", "slow_reveal"), "3 s: the short pair")
        self.assertEqual(brand["timing"]["shortened"], "short-effects")
        self.assertEqual(brand["frames"], {"entry": 20, "hold": 1, "exit": 12})
        self.assertEqual(brand["font"], sb.DEFAULT_FACE)
        self.assertEqual(brand["lines"][2], LONG)
        wanted = {2, 40, 70}                      # t = 0.08 s (before the entry), 1.67 s (the hold), 2.92 s (after the exit)
        meta, after, w, h = self.frames(target, wanted)
        _m, before, _w, _h = self.frames(self.source, wanted)
        self.assertEqual((w, h), (320, 180))
        self.assertTrue(meta.get("audio_codec"), "the sound came along")
        self.assertAlmostEqual(float(meta.get("duration") or 0), 3.0, delta=0.3)

        def band(ix, y0, y1):
            total = 0
            for y in range(y0, y1):
                a = after[ix][y * w * 3:(y + 1) * w * 3]
                b = before[ix][y * w * 3:(y + 1) * w * 3]
                total += sum(abs(x - z) for x, z in zip(a, b))
            return total / max(1, (y1 - y0) * w * 3)
        bottom_start, bottom_hold, bottom_end = band(2, h - h // 3, h), band(40, h - h // 3, h), band(70, h - h // 3, h)
        top_hold = band(40, 0, h // 4)
        self.assertLess(top_hold, 6.0, "the top of the picture is as it was")
        self.assertGreater(bottom_hold, 4.0, "the card is on the bottom third in the hold (a 320 px picture: ~7 measured)")
        self.assertLess(bottom_start, bottom_hold / 4, "no card before the entry")
        self.assertLess(bottom_end, bottom_hold / 4, "no card after the exit")
        print("\n[supercut-brand] real burn: frames %s, prepare %d ms, ffmpeg %d ms, whole %.2f s"
              % (brand["frames"], brand["render_ms"], brand.get("ffmpeg_ms") or 0, took))

    def test_a_one_second_clip_wears_the_card_from_its_first_frame(self):
        short = self.tmp / "short.mp4"
        subprocess.run([self.exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.source), "-t", "1",
                        "-c", "copy", str(short)], check=True, capture_output=True, timeout=60)
        target = self.tmp / "short-supercut.mp4"
        got = self.ns["h3_supercut_burn"](short, target, sb.lines(LONG), self.exe)
        self.assertEqual(got["brand"]["timing"]["shortened"], "hold-only")
        self.assertEqual(got["brand"]["frames"], {"entry": 0, "hold": 1, "exit": 0})
        _meta, after, w, h = self.frames(target, {0})
        _m, before, _w, _h = self.frames(short, {0})
        diff = sum(abs(x - z) for x, z in zip(after[0][(h - h // 3) * w * 3:], before[0][(h - h // 3) * w * 3:])) / (h // 3 * w * 3)
        self.assertGreater(diff, 4.0, "the card is on the first frame (a 320 px picture: ~7 measured)")


if __name__ == "__main__":
    unittest.main()
